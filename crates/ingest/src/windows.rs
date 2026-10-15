//! Win32 discovery and Windows Graphics Capture for a single HWND.

use std::collections::HashMap;
use std::ffi::c_void;
use std::mem::{size_of, size_of_val};
use std::path::Path;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use windows::core::{factory, Interface, BOOL, PWSTR};
use windows::Foundation::TypedEventHandler;
use windows::Graphics::Capture::{
    Direct3D11CaptureFrame, Direct3D11CaptureFramePool, GraphicsCaptureItem, GraphicsCaptureSession,
};
use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
use windows::Graphics::DirectX::DirectXPixelFormat;
use windows::Win32::Foundation::{
    CloseHandle, E_ACCESSDENIED, FILETIME, HANDLE, HMODULE, HWND, LPARAM, POINT, RECT, S_OK,
};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, ID3D11Texture2D, D3D11_CPU_ACCESS_READ,
    D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_MAPPED_SUBRESOURCE, D3D11_MAP_READ, D3D11_SDK_VERSION,
    D3D11_TEXTURE2D_DESC, D3D11_USAGE_STAGING,
};
use windows::Win32::Graphics::Dwm::{
    DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS,
};
use windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM;
use windows::Win32::Graphics::Dxgi::IDXGIDevice;
use windows::Win32::Graphics::Gdi::{
    BitBlt, CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GdiFlush, GetDC,
    ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, CAPTUREBLT, DIB_RGB_COLORS,
    HBITMAP, HDC, HGDIOBJ, SRCCOPY,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Performance::{QueryPerformanceCounter, QueryPerformanceFrequency};
use windows::Win32::System::StationsAndDesktops::{
    CloseDesktop, GetThreadDesktop, GetUserObjectInformationW, OpenInputDesktop,
    DESKTOP_CONTROL_FLAGS, DESKTOP_READOBJECTS, HDESK, UOI_NAME,
};
use windows::Win32::System::SystemInformation::OSVERSIONINFOW;
use windows::Win32::System::Threading::{
    GetCurrentThreadId, GetProcessTimes, OpenProcess, QueryFullProcessImageNameW,
    PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::System::WinRT::Direct3D11::{
    CreateDirect3D11DeviceFromDXGIDevice, IDirect3DDxgiInterfaceAccess,
};
use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;
use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetAncestor, GetClassNameW, GetClientRect, GetSystemMetrics, GetWindow,
    GetWindowLongPtrW, GetWindowRect, GetWindowTextLengthW, GetWindowTextW,
    GetWindowThreadProcessId, IsIconic, IsWindow, IsWindowVisible, WindowFromPoint, GA_ROOT,
    GA_ROOTOWNER, GWL_EXSTYLE, GWL_STYLE, GW_OWNER, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, WS_CAPTION, WS_CHILD, WS_EX_APPWINDOW, WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW, WS_POPUP, WS_SYSMENU, WS_THICKFRAME,
};

use crate::capture::{
    CaptureError, CapturedPopup, DiscoverySnapshot, Frame, FrameReadability, FrameVisibility,
    OwnedPopup, PixelSource, WindowInfo, MAX_OWNED_POPUPS,
};
use crate::discovery::ApplicationInfo;

const FRAME_POOL_BUFFERS: i32 = 2;
const FRAME_WAIT_TIMEOUT: Duration = Duration::from_millis(1500);

#[link(name = "ntdll")]
unsafe extern "system" {
    fn RtlGetVersion(info: *mut OSVERSIONINFOW) -> i32;
}

fn check_os() -> Result<(), CaptureError> {
    let mut info = OSVERSIONINFOW {
        dwOSVersionInfoSize: size_of::<OSVERSIONINFOW>() as u32,
        ..Default::default()
    };
    // SAFETY: RtlGetVersion writes to the correctly sized, initialized Win32 structure.
    let status = unsafe { RtlGetVersion(&mut info) };
    if status != 0 {
        return Err(CaptureError::Backend(format!(
            "RtlGetVersion failed: 0x{status:08x}"
        )));
    }
    if info.dwMajorVersion < 10 || (info.dwMajorVersion == 10 && info.dwBuildNumber < 18362) {
        return Err(CaptureError::UnsupportedWindowsVersion);
    }
    Ok(())
}

fn backend(error: windows::core::Error) -> CaptureError {
    if error.code() == E_ACCESSDENIED {
        CaptureError::PermissionDenied
    } else {
        CaptureError::Backend(format!("0x{:08x}: {error}", error.code().0 as u32))
    }
}

struct OwnedHandle(HANDLE);

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        // SAFETY: This object owns a successful OpenProcess or Toolhelp handle.
        let _ = unsafe { CloseHandle(self.0) };
    }
}

fn processes() -> Result<HashMap<u32, String>, CaptureError> {
    // SAFETY: Snapshot handle is closed by OwnedHandle; entry size is set before calls.
    let snapshot =
        OwnedHandle(unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }.map_err(backend)?);
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let mut result = HashMap::new();
    if unsafe { Process32FirstW(snapshot.0, &mut entry) }.is_ok() {
        loop {
            let end = entry
                .szExeFile
                .iter()
                .position(|&ch| ch == 0)
                .unwrap_or(entry.szExeFile.len());
            let exe = String::from_utf16_lossy(&entry.szExeFile[..end]);
            if entry.th32ProcessID != 0 && !exe.is_empty() {
                result.insert(entry.th32ProcessID, exe);
            }
            // No next entry is normal completion; all other metadata remains usable.
            if unsafe { Process32NextW(snapshot.0, &mut entry) }.is_err() {
                break;
            }
        }
    }
    Ok(result)
}

fn process_exe_name(pid: u32) -> Option<String> {
    // SAFETY: OpenProcess requests only image-path query rights. Handle is closed.
    let handle =
        OwnedHandle(unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?);
    let mut path = vec![0u16; 32768];
    let mut len = path.len() as u32;
    unsafe {
        QueryFullProcessImageNameW(
            handle.0,
            PROCESS_NAME_WIN32,
            PWSTR(path.as_mut_ptr()),
            &mut len,
        )
    }
    .ok()?;
    let path = String::from_utf16(&path[..len as usize]).ok()?;
    Path::new(&path).file_name()?.to_str().map(str::to_owned)
}

fn process_created_at_100ns(pid: u32) -> Option<u64> {
    // SAFETY: Query-only owned handle and caller-owned output structures.
    let handle =
        OwnedHandle(unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?);
    let (mut created, mut exited, mut kernel, mut user) = (
        FILETIME::default(),
        FILETIME::default(),
        FILETIME::default(),
        FILETIME::default(),
    );
    unsafe { GetProcessTimes(handle.0, &mut created, &mut exited, &mut kernel, &mut user) }.ok()?;
    let created = (u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime);
    (created > 0).then_some(created)
}

pub(crate) fn verify_visible_window(selected: &WindowInfo) -> Result<u64, CaptureError> {
    verify_window(selected)?;
    process_created_at_100ns(selected.process_id).ok_or(CaptureError::StaleWindow {
        hwnd: selected.hwnd,
    })
}

fn window_uncloaked(hwnd: HWND) -> bool {
    let mut cloaked = 0u32;
    // SAFETY: Read-only DWM visibility query; unsupported/error fails closed.
    unsafe {
        DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            (&mut cloaked as *mut u32).cast(),
            size_of::<u32>() as u32,
        )
    }
    .is_ok()
        && cloaked == 0
}

fn window_metadata(hwnd: HWND, exe_name: String) -> Option<WindowInfo> {
    // SAFETY: Win32 calls query one HWND and write into caller-owned buffers.
    if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        return None;
    }
    let mut pid = 0;
    if unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) } == 0 || pid == 0 {
        return None;
    }
    let title_len = unsafe { GetWindowTextLengthW(hwnd) }.clamp(0, 4095) as usize;
    let mut title_buffer = vec![0u16; title_len + 1];
    let copied = unsafe { GetWindowTextW(hwnd, &mut title_buffer) }.max(0) as usize;
    let title = (copied > 0).then(|| String::from_utf16_lossy(&title_buffer[..copied]));
    let mut rect = RECT::default();
    unsafe { GetWindowRect(hwnd, &mut rect) }.ok()?;
    let width = rect.right.saturating_sub(rect.left) as u32;
    let height = rect.bottom.saturating_sub(rect.top) as u32;
    let on_screen = unsafe { IsWindowVisible(hwnd).as_bool() && !IsIconic(hwnd).as_bool() }
        && window_uncloaked(hwnd);
    Some(WindowInfo {
        hwnd: hwnd.0 as usize,
        process_id: pid,
        exe_name,
        title,
        on_screen,
        width,
        height,
    })
}

struct EnumContext<'a> {
    processes: &'a HashMap<u32, String>,
    windows: Vec<WindowInfo>,
}

unsafe extern "system" fn enum_window(hwnd: HWND, lparam: LPARAM) -> BOOL {
    // SAFETY: EnumWindows invokes this callback synchronously while the context lives.
    let context = unsafe { &mut *(lparam.0 as *mut EnumContext<'_>) };
    let mut pid = 0;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    if let Some(exe_name) = context.processes.get(&pid) {
        if let Some(window) = window_metadata(hwnd, exe_name.clone()) {
            context.windows.push(window);
        }
    }
    BOOL(1)
}

pub(crate) fn discover() -> Result<DiscoverySnapshot, CaptureError> {
    check_os()?;
    verify_input_desktop()?;
    let process_map = processes()?;
    let applications = process_map
        .iter()
        .map(|(&process_id, exe_name)| ApplicationInfo {
            exe_name: exe_name.clone(),
            process_id,
        })
        .collect();
    let mut context = EnumContext {
        processes: &process_map,
        windows: Vec::new(),
    };
    // SAFETY: Callback and its borrowed context remain valid until EnumWindows returns.
    unsafe {
        EnumWindows(
            Some(enum_window),
            LPARAM((&mut context as *mut EnumContext<'_>) as isize),
        )
    }
    .map_err(backend)?;
    Ok(DiscoverySnapshot {
        applications,
        windows: context.windows,
    })
}

pub(crate) fn verify_window(selected: &WindowInfo) -> Result<(), CaptureError> {
    let hwnd = HWND(selected.hwnd as *mut c_void);
    let exe_name = process_exe_name(selected.process_id).ok_or(CaptureError::StaleWindow {
        hwnd: selected.hwnd,
    })?;
    let current = window_metadata(hwnd, exe_name).ok_or(CaptureError::StaleWindow {
        hwnd: selected.hwnd,
    })?;
    if current.hwnd != selected.hwnd
        || current.process_id != selected.process_id
        || !current.exe_name.eq_ignore_ascii_case(&selected.exe_name)
        || current.title != selected.title
        || !current.on_screen
        || current.width != selected.width
        || current.height != selected.height
    {
        return Err(CaptureError::StaleWindow {
            hwnd: selected.hwnd,
        });
    }
    Ok(())
}

fn rectangles_overlap(a: &RECT, b: &RECT) -> bool {
    a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}

fn verify_input_desktop() -> Result<(), CaptureError> {
    // Only read object names. Never create windows, switch desktops or alter access.
    // SAFETY: Owned read-only input-desktop handle is closed on every path below.
    let input = unsafe { OpenInputDesktop(DESKTOP_CONTROL_FLAGS(0), false, DESKTOP_READOBJECTS) }
        .map_err(backend)?;
    let result = (|| {
        // SAFETY: Borrow the current thread desktop, which must not be closed here.
        let current = unsafe { GetThreadDesktop(GetCurrentThreadId()) }.map_err(backend)?;
        let name = |desktop: HDESK| -> Result<Vec<u16>, CaptureError> {
            let mut buffer = [0u16; 256];
            // SAFETY: Fixed writable UTF-16 buffer, bounded in bytes by its allocation.
            unsafe {
                GetUserObjectInformationW(
                    HANDLE(desktop.0),
                    UOI_NAME,
                    Some(buffer.as_mut_ptr().cast()),
                    size_of_val(&buffer) as u32,
                    None,
                )
            }
            .map_err(backend)?;
            let length = buffer
                .iter()
                .position(|value| *value == 0)
                .filter(|length| *length > 0)
                .ok_or_else(|| CaptureError::Backend("unknown input desktop".into()))?;
            Ok(buffer[..length].to_vec())
        };
        if name(current)? != name(input)? {
            return Err(CaptureError::Backend(
                "capture thread is not on the active input desktop".into(),
            ));
        }
        Ok(())
    })();
    // SAFETY: This function owns input, independently of the borrowed thread desktop.
    let closed = unsafe { CloseDesktop(input) }.map_err(backend);
    result.and(closed)
}

#[derive(Debug, Clone, PartialEq)]
struct SurfaceWindow {
    hwnd: usize,
    process_id: u32,
    process_created_at_100ns: Option<u64>,
    owner: usize,
    root: usize,
    root_owner: usize,
    root_owner_process_id: u32,
    class: String,
    style: u32,
    ex_style: u32,
    rect: RECT,
}

fn surface_window(hwnd: HWND, rect: RECT, selected_pid: u32) -> SurfaceWindow {
    let mut process_id = 0;
    let mut class = [0u16; 256];
    // SAFETY: Read-only HWND metadata, with a bounded caller-owned class buffer.
    let (length, owner, root, root_owner, style, ex_style) = unsafe {
        GetWindowThreadProcessId(hwnd, Some(&mut process_id));
        (
            GetClassNameW(hwnd, &mut class),
            GetWindow(hwnd, GW_OWNER).unwrap_or_default(),
            GetAncestor(hwnd, GA_ROOT),
            GetAncestor(hwnd, GA_ROOTOWNER),
            GetWindowLongPtrW(hwnd, GWL_STYLE) as u32,
            GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32,
        )
    };
    SurfaceWindow {
        hwnd: hwnd.0 as usize,
        process_id,
        process_created_at_100ns: (process_id == selected_pid)
            .then(|| process_created_at_100ns(process_id))
            .flatten(),
        owner: owner.0 as usize,
        root: root.0 as usize,
        root_owner: root_owner.0 as usize,
        root_owner_process_id: {
            let mut pid = 0;
            // SAFETY: Query the already obtained root-owner HWND, not an input action.
            unsafe { GetWindowThreadProcessId(root_owner, Some(&mut pid)) };
            pid
        },
        class: if (1..255).contains(&length) {
            String::from_utf16(&class[..length as usize]).unwrap_or_default()
        } else {
            String::new()
        },
        style,
        ex_style,
        rect,
    }
}

fn valid_surface_rect(rect: &RECT, desktop: &RECT) -> bool {
    rect.right.checked_sub(rect.left).is_some_and(|n| n > 0)
        && rect.bottom.checked_sub(rect.top).is_some_and(|n| n > 0)
        && rect.left >= desktop.left
        && rect.top >= desktop.top
        && rect.right <= desktop.right
        && rect.bottom <= desktop.bottom
}

fn proven_empty_footprint(
    window_rect: Option<RECT>,
    client_rect: Option<RECT>,
    extended_frame_bounds: Option<RECT>,
) -> bool {
    [window_rect, client_rect, extended_frame_bounds]
        .into_iter()
        .all(|rect| rect == Some(RECT::default()))
}

/// One bounded, single-line private backend error, not an enumerated window dump.
fn surface_error(
    cause: &'static str,
    offender: &SurfaceWindow,
    reference: &SurfaceWindow,
) -> CaptureError {
    let describe = |window: &SurfaceWindow| {
        let class: String = window
            .class
            .chars()
            .take(64)
            .map(|character| {
                if character.is_ascii_graphic() && !matches!(character, '\\' | '"') {
                    character
                } else {
                    '?'
                }
            })
            .collect();
        format!(
            "hwnd=0x{:x} pid={} class=\"{}\" owner=0x{:x} root=0x{:x} root_owner=0x{:x} rect=[{},{},{},{}]",
            window.hwnd, window.process_id, class, window.owner, window.root, window.root_owner,
            window.rect.left, window.rect.top, window.rect.right, window.rect.bottom,
        )
    };
    CaptureError::Backend(format!(
        "selected window surface is obscured or ambiguous: cause={cause} offender=({}) reference=({})",
        describe(offender), describe(reference),
    ))
}

/// Only exact selected ownership plus a transient class/style can grant an
/// exception. A shared process/root owner or executable is never sufficient.
fn owned_transient(selected: &SurfaceWindow, other: &SurfaceWindow) -> Option<OwnedPopup> {
    let instance = selected.process_created_at_100ns.filter(|n| *n > 0)?;
    let native_transient =
        other.class.eq_ignore_ascii_case("tooltips_class32") || other.class == "#32768";
    let tool_window = other.ex_style & (WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0) != 0;
    if selected.hwnd == 0
        || selected.root != selected.hwnd
        || selected.root_owner == 0
        || selected.root_owner_process_id != selected.process_id
        || selected.class.is_empty()
        || other.hwnd == 0
        || other.hwnd == selected.hwnd
        || other.process_id != selected.process_id
        || other.process_id == 0
        || other.process_created_at_100ns != Some(instance)
        || other.owner != selected.hwnd
        || other.root != other.hwnd
        || other.root_owner != selected.root_owner
        || other.root_owner_process_id != selected.process_id
        || other.class.is_empty()
        || other.class.eq_ignore_ascii_case(&selected.class)
        || other.class.eq_ignore_ascii_case("UnityWndClass")
        || other.class.eq_ignore_ascii_case("Chrome_WidgetWin_1")
        || other.style & WS_POPUP.0 == 0
        || other.style & (WS_CHILD.0 | WS_CAPTION.0 | WS_SYSMENU.0 | WS_THICKFRAME.0) != 0
        || other.ex_style & WS_EX_APPWINDOW.0 != 0
        || !(native_transient || tool_window)
    {
        return None;
    }
    let relative = |value: i32, origin: i32| i64::from(value) - i64::from(origin);
    Some(OwnedPopup {
        hwnd: other.hwnd,
        owner_hwnd: other.owner,
        root_owner_hwnd: other.root_owner,
        process_id: other.process_id,
        process_created_at_100ns: instance,
        window_class: other.class.clone(),
        relative_bounds: [
            relative(other.rect.left, selected.rect.left),
            relative(other.rect.top, selected.rect.top),
            relative(other.rect.right, selected.rect.left),
            relative(other.rect.bottom, selected.rect.top),
        ],
    })
}

#[derive(Debug, Clone, PartialEq)]
struct VisibleSurface {
    selected: SurfaceWindow,
    popups: Vec<(SurfaceWindow, OwnedPopup)>,
    occluded_regions: Vec<[u32; 4]>,
}

fn unchanged_surface(
    before: &VisibleSurface,
    after: &VisibleSurface,
) -> Result<bool, CaptureError> {
    if before.selected != after.selected {
        return Err(CaptureError::StaleWindow {
            hwnd: before.selected.hwnd,
        });
    }
    Ok(before == after)
}

fn classify_visible_surface(
    selected: SurfaceWindow,
    above: &[SurfaceWindow],
    center_hit: &SurfaceWindow,
    desktop: &RECT,
    expected_instance: u64,
) -> Result<VisibleSurface, CaptureError> {
    if expected_instance == 0
        || selected.process_created_at_100ns != Some(expected_instance)
        || selected.root != selected.hwnd
        || selected.root_owner == 0
        || selected.class.is_empty()
        || selected.root_owner_process_id != selected.process_id
        || !valid_surface_rect(&selected.rect, desktop)
    {
        return Err(CaptureError::StaleWindow {
            hwnd: selected.hwnd,
        });
    }
    let mut popups = Vec::new();
    for other in above {
        // Only separately proven empty surfaces may be omitted by the collector.
        if other.rect.right <= other.rect.left || other.rect.bottom <= other.rect.top {
            return Err(surface_error("nonpositive-geometry", other, &selected));
        }
        if let Some(popup) = owned_transient(&selected, other) {
            if !valid_surface_rect(&other.rect, desktop) {
                return Err(surface_error("popup-geometry", other, &selected));
            }
            if popups.len() == MAX_OWNED_POPUPS {
                return Err(surface_error("popup-limit", other, &selected));
            }
            popups.push((other.clone(), popup));
        }
    }
    for other in above {
        let is_owned = popups.iter().any(|(window, _)| window.hwnd == other.hwnd);
        if !is_owned {
            if rectangles_overlap(&selected.rect, &other.rect) {
                return Err(surface_error("foreign-overlap", other, &selected));
            }
            if let Some((window, _)) = popups
                .iter()
                .find(|(window, _)| rectangles_overlap(&window.rect, &other.rect))
            {
                return Err(surface_error("popup-overlap", other, window));
            }
        }
    }
    // A second popup over the first does not prove that its full pixels are visible.
    for (index, (window, _)) in popups.iter().enumerate() {
        if let Some((other, _)) = popups[..index]
            .iter()
            .find(|(other, _)| rectangles_overlap(&window.rect, &other.rect))
        {
            return Err(surface_error("popup-overlap", other, window));
        }
    }
    let center = (
        i64::from(selected.rect.left)
            + (i64::from(selected.rect.right) - i64::from(selected.rect.left)) / 2,
        i64::from(selected.rect.top)
            + (i64::from(selected.rect.bottom) - i64::from(selected.rect.top)) / 2,
    );
    if center_hit.hwnd != selected.hwnd
        && !popups.iter().any(|(window, _)| {
            window.hwnd == center_hit.hwnd
                && center.0 >= i64::from(window.rect.left)
                && center.0 < i64::from(window.rect.right)
                && center.1 >= i64::from(window.rect.top)
                && center.1 < i64::from(window.rect.bottom)
        })
    {
        return Err(surface_error("center-mismatch", center_hit, &selected));
    }
    let mut occluded_regions = Vec::new();
    for (window, _) in &popups {
        if rectangles_overlap(&selected.rect, &window.rect) {
            occluded_regions.push([
                (i64::from(window.rect.left.max(selected.rect.left))
                    - i64::from(selected.rect.left)) as u32,
                (i64::from(window.rect.top.max(selected.rect.top)) - i64::from(selected.rect.top))
                    as u32,
                (i64::from(window.rect.right.min(selected.rect.right))
                    - i64::from(selected.rect.left)) as u32,
                (i64::from(window.rect.bottom.min(selected.rect.bottom))
                    - i64::from(selected.rect.top)) as u32,
            ]);
        }
    }
    Ok(VisibleSurface {
        selected,
        popups,
        occluded_regions,
    })
}

fn visible_surface(
    selected: &WindowInfo,
    expected_instance: u64,
) -> Result<VisibleSurface, CaptureError> {
    verify_input_desktop()?;
    verify_window(selected)?;
    let hwnd = HWND(selected.hwnd as *mut c_void);
    let mut rect = RECT::default();
    // SAFETY: Read-only metadata for the revalidated selected window.
    unsafe { GetWindowRect(hwnd, &mut rect) }.map_err(backend)?;
    let window = surface_window(hwnd, rect, selected.process_id);
    struct Visibility {
        hwnd: HWND,
        selected: SurfaceWindow,
        above: Vec<SurfaceWindow>,
        found: bool,
        blocked: Option<CaptureError>,
    }
    unsafe extern "system" fn above_window(hwnd: HWND, lparam: LPARAM) -> BOOL {
        // SAFETY: EnumWindows is synchronous; the caller owns this context.
        let visibility = unsafe { &mut *(lparam.0 as *mut Visibility) };
        if hwnd == visibility.hwnd {
            visibility.found = true;
        } else if !visibility.found
            && unsafe { IsWindowVisible(hwnd).as_bool() && !IsIconic(hwnd).as_bool() }
        {
            let mut other = RECT::default();
            let mut cloaked = 0u32;
            // SAFETY: Read-only geometry and DWM query. Unknown overlaps fail closed.
            let rect_result = unsafe { GetWindowRect(hwnd, &mut other) };
            let cloak_result = unsafe {
                DwmGetWindowAttribute(
                    hwnd,
                    DWMWA_CLOAKED,
                    (&mut cloaked as *mut u32).cast(),
                    size_of::<u32>() as u32,
                )
            };
            if rect_result.is_err() || cloak_result.is_err() {
                let offender = surface_window(hwnd, other, visibility.selected.process_id);
                let cause = if rect_result.is_err() {
                    "window-geometry-query-failed"
                } else {
                    "cloak-query-failed"
                };
                visibility
                    .blocked
                    .get_or_insert_with(|| surface_error(cause, &offender, &visibility.selected));
            } else if cloaked == 0 {
                if other == RECT::default() {
                    let mut client = RECT::default();
                    let mut extended = RECT::default();
                    // SAFETY: Synchronous read-only queries with caller-owned rectangles.
                    let client_result = unsafe { GetClientRect(hwnd, &mut client) };
                    let extended_result = unsafe {
                        DwmGetWindowAttribute(
                            hwnd,
                            DWMWA_EXTENDED_FRAME_BOUNDS,
                            (&mut extended as *mut RECT).cast(),
                            size_of::<RECT>() as u32,
                        )
                    };
                    if proven_empty_footprint(
                        Some(other),
                        client_result.ok().map(|_| client),
                        extended_result.ok().map(|_| extended),
                    ) {
                        // Every pre/post desktop-copy rescan repeats this proof.
                        return BOOL(1);
                    }
                }
                visibility
                    .above
                    .push(surface_window(hwnd, other, visibility.selected.process_id));
            }
        }
        BOOL(1)
    }
    let mut visibility = Visibility {
        hwnd,
        selected: window.clone(),
        above: Vec::new(),
        found: false,
        blocked: None,
    };
    // Drawable and unknown surfaces above the source remain in full-popup Z-order checks.
    // SAFETY: Context and callback live until the synchronous call returns.
    unsafe {
        EnumWindows(
            Some(above_window),
            LPARAM((&mut visibility as *mut Visibility) as isize),
        )
    }
    .map_err(backend)?;
    if let Some(error) = visibility.blocked {
        return Err(error);
    }
    if !visibility.found {
        return Err(surface_error("selected-not-enumerated", &window, &window));
    }
    let center = POINT {
        x: (i64::from(rect.left) + (i64::from(rect.right) - i64::from(rect.left)) / 2) as i32,
        y: (i64::from(rect.top) + (i64::from(rect.bottom) - i64::from(rect.top)) / 2) as i32,
    };
    // SAFETY: Read-only hit test and virtual-desktop dimensions.
    let (center_root, left, top, width, height) = unsafe {
        (
            GetAncestor(WindowFromPoint(center), GA_ROOT).0 as usize,
            GetSystemMetrics(SM_XVIRTUALSCREEN),
            GetSystemMetrics(SM_YVIRTUALSCREEN),
            GetSystemMetrics(SM_CXVIRTUALSCREEN),
            GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )
    };
    let desktop = RECT {
        left,
        top,
        right: left
            .checked_add(width)
            .filter(|_| width > 0)
            .ok_or_else(|| CaptureError::Backend("unknown desktop geometry".into()))?,
        bottom: top
            .checked_add(height)
            .filter(|_| height > 0)
            .ok_or_else(|| CaptureError::Backend("unknown desktop geometry".into()))?,
    };
    let center_hit = if center_root == window.hwnd {
        window.clone()
    } else if let Some(known) = visibility
        .above
        .iter()
        .find(|other| other.hwnd == center_root)
    {
        known.clone()
    } else {
        let center_hwnd = HWND(center_root as *mut c_void);
        let mut center_rect = RECT::default();
        // SAFETY: Read-only diagnostic of the actual hit-root, never an input action.
        let _ = unsafe { GetWindowRect(center_hwnd, &mut center_rect) };
        surface_window(center_hwnd, center_rect, selected.process_id)
    };
    classify_visible_surface(
        window,
        &visibility.above,
        &center_hit,
        &desktop,
        expected_instance,
    )
}

#[derive(Default)]
struct ScreenBitmap {
    screen: HDC,
    memory: HDC,
    bitmap: HBITMAP,
    previous: HGDIOBJ,
}

impl Drop for ScreenBitmap {
    fn drop(&mut self) {
        // SAFETY: Owned handles; restore the old bitmap before deleting this one.
        unsafe {
            if !self.previous.is_invalid() && !self.memory.is_invalid() {
                SelectObject(self.memory, self.previous);
            }
            if !self.bitmap.is_invalid() {
                let _ = DeleteObject(HGDIOBJ(self.bitmap.0));
            }
            if !self.memory.is_invalid() {
                let _ = DeleteDC(self.memory);
            }
            if !self.screen.is_invalid() {
                ReleaseDC(None, self.screen);
            }
        }
    }
}

pub(crate) fn capture_visible_frame(
    selected: &WindowInfo,
    expected_instance: u64,
) -> Result<Frame, CaptureError> {
    check_os()?;
    // A positively owned panel can appear during a copy. Discard that entire
    // attempt and recopy once under the SAME caller clock/lease. Unknown or
    // foreign overlaps and changed selected identity still fail immediately.
    'capture: for _ in 0..2 {
        let surface = visible_surface(selected, expected_instance)?;
        let mut frame = copy_desktop_rect(&surface.selected.rect)?;
        if !unchanged_surface(&surface, &visible_surface(selected, expected_instance)?)? {
            continue;
        }
        frame.visibility = FrameVisibility {
            pixel_source: PixelSource::VisibleDesktopPixels,
            source_process_created_at_100ns: Some(expected_instance),
            readability: if surface.occluded_regions.is_empty() {
                FrameReadability::Full
            } else {
                FrameReadability::Regional
            },
            occluded_regions: surface.occluded_regions.clone(),
            owned_popups: surface
                .popups
                .iter()
                .map(|(_, proof)| proof.clone())
                .collect(),
        };
        for (window, proof) in &surface.popups {
            let [l, t, r, b] = proof.relative_bounds;
            if l < 0 || t < 0 || r > i64::from(frame.width) || b > i64::from(frame.height) {
                let started = Instant::now();
                let source_utc_unix_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .ok()
                    .and_then(|duration| u64::try_from(duration.as_millis()).ok())
                    .ok_or_else(|| CaptureError::Backend("invalid popup capture clock".into()))?;
                let mut pixels = copy_desktop_rect(&window.rect)?;
                let total = frame
                    .rgba
                    .len()
                    .checked_add(pixels.rgba.len())
                    .and_then(|n| {
                        frame
                            .popup_frames
                            .iter()
                            .try_fold(n, |total, popup| total.checked_add(popup.frame.rgba.len()))
                    });
                if total.is_none_or(|n| n > 64 * 1024 * 1024) {
                    return Err(CaptureError::Backend(
                        "owned popup capture bytes exceed bounded frame work".into(),
                    ));
                }
                pixels.visibility.pixel_source = PixelSource::VisibleDesktopPixels;
                pixels.visibility.source_process_created_at_100ns = Some(expected_instance);
                if !unchanged_surface(&surface, &visible_surface(selected, expected_instance)?)? {
                    continue 'capture;
                }
                frame.popup_frames.push(CapturedPopup {
                    window: proof.clone(),
                    frame: Box::new(pixels),
                    source_utc_unix_ms,
                    started,
                });
            }
        }
        frame
            .validate()
            .map_err(|error| CaptureError::Backend(error.to_string()))?;
        return Ok(frame);
    }
    Err(CaptureError::StaleWindow {
        hwnd: selected.hwnd,
    })
}

fn copy_desktop_rect(rect: &RECT) -> Result<Frame, CaptureError> {
    let width = rect.right.checked_sub(rect.left).filter(|n| *n > 0);
    let height = rect.bottom.checked_sub(rect.top).filter(|n| *n > 0);
    let (Some(width), Some(height)) = (width, height) else {
        return Err(CaptureError::Backend(
            "invalid visible window geometry".into(),
        ));
    };
    let bytes = (width as usize)
        .checked_mul(height as usize)
        .and_then(|n| n.checked_mul(4))
        .filter(|n| *n <= 256 * 1024 * 1024)
        .ok_or_else(|| CaptureError::Backend("visible window frame is too large".into()))?;
    // SAFETY: Desktop DC is read-only; only the validated window rectangle is copied.
    let mut owned = ScreenBitmap {
        screen: unsafe { GetDC(None) },
        ..Default::default()
    };
    if owned.screen.is_invalid() {
        return Err(CaptureError::Backend("desktop DC unavailable".into()));
    }
    owned.memory = unsafe { CreateCompatibleDC(Some(owned.screen)) };
    if owned.memory.is_invalid() {
        return Err(CaptureError::Backend(
            "capture bitmap DC unavailable".into(),
        ));
    }
    let info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width,
            biHeight: -height,
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB.0,
            ..Default::default()
        },
        ..Default::default()
    };
    let mut bits = std::ptr::null_mut();
    // SAFETY: Header specifies a bounded top-down 32-bit bitmap; pointer is owned by bitmap.
    owned.bitmap = unsafe {
        CreateDIBSection(
            Some(owned.screen),
            &info,
            DIB_RGB_COLORS,
            &mut bits,
            None,
            0,
        )
    }
    .map_err(backend)?;
    owned.previous = unsafe { SelectObject(owned.memory, HGDIOBJ(owned.bitmap.0)) };
    if owned.previous.is_invalid() || bits.is_null() {
        return Err(CaptureError::Backend(
            "capture bitmap selection failed".into(),
        ));
    }
    // This is a new synchronous read of current displayed pixels, not an old WGC surface.
    // SAFETY: Both DCs and the destination bitmap remain owned until the copy completes.
    unsafe {
        BitBlt(
            owned.memory,
            0,
            0,
            width,
            height,
            Some(owned.screen),
            rect.left,
            rect.top,
            SRCCOPY | CAPTUREBLT,
        )
    }
    .map_err(backend)?;
    if !unsafe { GdiFlush() }.as_bool() {
        return Err(CaptureError::Backend("capture bitmap flush failed".into()));
    }
    // SAFETY: CreateDIBSection allocated the bounded byte count described by info.
    let mut rgba = unsafe { std::slice::from_raw_parts(bits as *const u8, bytes) }.to_vec();
    for pixel in rgba.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        pixel[3] = 255;
    }
    Frame::new(width as u32, height as u32, rgba)
        .map_err(|error| CaptureError::Backend(error.to_string()))
}

struct Apartment;

impl Apartment {
    fn new() -> Result<Self, CaptureError> {
        // SAFETY: Paired with RoUninitialize in Drop on the selecting thread.
        unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.map_err(backend)?;
        Ok(Self)
    }
}

impl Drop for Apartment {
    fn drop(&mut self) {
        // SAFETY: Each successful RoInitialize has one matching release.
        unsafe { RoUninitialize() };
    }
}

struct OwnedCaptureFrame(Direct3D11CaptureFrame);

impl Drop for OwnedCaptureFrame {
    fn drop(&mut self) {
        // Return buffers even on timestamp/copy errors or when superseded.
        let _ = self.0.Close();
    }
}

/// Field order is drop order. The session and frame pool must be released
/// before the D3D device, and COM must be released before `RoUninitialize`.
pub(crate) struct WindowsCapturer {
    session: GraphicsCaptureSession,
    pool: Direct3D11CaptureFramePool,
    context: ID3D11DeviceContext,
    device: ID3D11Device,
    direct3d: IDirect3DDevice,
    item: GraphicsCaptureItem,
    frame_event: i64,
    arrived: Receiver<()>,
    seen_frame: bool,
    selected: WindowInfo,
    _apartment: Apartment,
}

impl WindowsCapturer {
    pub(crate) fn for_window(selected: &WindowInfo) -> Result<Self, CaptureError> {
        check_os()?;
        verify_window(selected)?;
        let apartment = Apartment::new()?;
        if !GraphicsCaptureSession::IsSupported().map_err(backend)? {
            return Err(CaptureError::Backend(
                "Windows Graphics Capture is unavailable".into(),
            ));
        }
        let interop =
            factory::<GraphicsCaptureItem, IGraphicsCaptureItemInterop>().map_err(backend)?;
        // SAFETY: HWND identity was checked immediately above; rechecked after item creation.
        let item: GraphicsCaptureItem =
            unsafe { interop.CreateForWindow(HWND(selected.hwnd as *mut c_void)) }
                .map_err(backend)?;
        verify_window(selected)?;
        let mut device = None;
        let mut context = None;
        // SAFETY: Out pointers refer to initialized Option slots; hardware D3D11 only.
        unsafe {
            D3D11CreateDevice(
                None,
                D3D_DRIVER_TYPE_HARDWARE,
                HMODULE::default(),
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                None,
                D3D11_SDK_VERSION,
                Some(&mut device),
                None,
                Some(&mut context),
            )
        }
        .map_err(backend)?;
        let device: ID3D11Device =
            device.ok_or_else(|| CaptureError::Backend("D3D11 returned no device".into()))?;
        let context: ID3D11DeviceContext =
            context.ok_or_else(|| CaptureError::Backend("D3D11 returned no context".into()))?;
        let dxgi: IDXGIDevice = device.cast().map_err(backend)?;
        // SAFETY: DXGI device remains alive for the lifetime of the WinRT wrapper.
        let direct3d = unsafe { CreateDirect3D11DeviceFromDXGIDevice(&dxgi) }
            .map_err(backend)?
            .cast::<IDirect3DDevice>()
            .map_err(backend)?;
        let (pool, session, frame_event, arrived) = start_session(&direct3d, &item)?;
        Ok(Self {
            selected: selected.clone(),
            item,
            direct3d,
            device,
            context,
            pool,
            session,
            frame_event,
            arrived,
            seen_frame: false,
            _apartment: apartment,
        })
    }

    pub(crate) fn capture(&mut self) -> Result<Frame, CaptureError> {
        let started = Instant::now();
        let mut frequency = 0;
        // SAFETY: QueryPerformanceFrequency writes to a caller-owned i64.
        unsafe { QueryPerformanceFrequency(&mut frequency) }.map_err(backend)?;
        let cutoff_qpc = qpc_now()?;
        if frequency <= 0 {
            return Err(CaptureError::Backend("invalid QPC frequency".into()));
        }
        verify_window(&self.selected)?;
        let mut restarted = false;
        loop {
            let recover_if_empty = needs_fresh_session(&self.arrived, self.seen_frame)?;
            let mut newest: Option<(i64, OwnedCaptureFrame)> = None;
            let mut discarded = false;
            // Drain at most the pool capacity, even if the producer keeps filling
            // returned buffers. Arrival notifications are only wakeups, not proof
            // that the pixels were rendered during this capture invocation.
            for _ in 0..FRAME_POOL_BUFFERS {
                remaining_frame_wait(started.elapsed())?;
                let captured = match self.pool.TryGetNextFrame() {
                    Ok(frame) => OwnedCaptureFrame(frame),
                    // windows 0.62 projects a successful null (empty pool) as
                    // Error::empty(), whose HRESULT is S_OK, not E_POINTER.
                    Err(error) if error.code() == S_OK => break,
                    Err(error) => return Err(backend(error)),
                };
                let timestamp = captured.0.SystemRelativeTime().map_err(backend)?.Duration;
                if newer_fresh_timestamp(
                    timestamp,
                    newest.as_ref().map(|(time, _)| *time),
                    cutoff_qpc,
                    qpc_now()?,
                    frequency,
                ) {
                    newest = Some((timestamp, captured));
                } else {
                    discarded = true;
                }
            }
            remaining_frame_wait(started.elapsed())?;
            if let Some((_, captured)) = newest {
                let result = self.copy_frame(&captured.0);
                drop(captured);
                let mut frame = result?;
                verify_window(&self.selected)?;
                frame.visibility.pixel_source = PixelSource::SelectedWindowSurface;
                self.seen_frame = true;
                return Ok(frame);
            }
            if !restarted && (recover_if_empty || discarded) {
                // A queued notification can outlive its frame. If draining found
                // no fresh frame, it must not prevent static-window recovery. Recreate once,
                // without resetting either the QPC cutoff or the wait budget.
                self.restart_session()?;
                restarted = true;
                continue;
            }
            self.arrived
                .recv_timeout(remaining_frame_wait(started.elapsed())?)
                .map_err(|_| {
                    CaptureError::Backend("timed out waiting for a fresh window frame".into())
                })?;
        }
    }

    fn restart_session(&mut self) -> Result<(), CaptureError> {
        let _ = self.pool.RemoveFrameArrived(self.frame_event);
        let _ = self.session.Close();
        let _ = self.pool.Close();
        let (pool, session, frame_event, arrived) = start_session(&self.direct3d, &self.item)?;
        self.session = session;
        self.pool = pool;
        self.frame_event = frame_event;
        self.arrived = arrived;
        Ok(())
    }

    fn copy_frame(&self, captured: &Direct3D11CaptureFrame) -> Result<Frame, CaptureError> {
        let size = captured.ContentSize().map_err(backend)?;
        let width = u32::try_from(size.Width)
            .ok()
            .filter(|&n| n > 0)
            .ok_or_else(|| CaptureError::Backend("invalid frame width".into()))?;
        let height = u32::try_from(size.Height)
            .ok()
            .filter(|&n| n > 0)
            .ok_or_else(|| CaptureError::Backend("invalid frame height".into()))?;
        let surface = captured.Surface().map_err(backend)?;
        let access: IDirect3DDxgiInterfaceAccess = surface.cast().map_err(backend)?;
        // SAFETY: WGC owns the GPU surface until captured is closed below.
        let texture: ID3D11Texture2D = unsafe { access.GetInterface() }.map_err(backend)?;
        let mut desc = D3D11_TEXTURE2D_DESC::default();
        // SAFETY: desc is a valid caller-owned output structure.
        unsafe { texture.GetDesc(&mut desc) };
        if desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM || width > desc.Width || height > desc.Height {
            return Err(CaptureError::Backend(
                "unexpected WGC surface format or size".into(),
            ));
        }
        desc.Usage = D3D11_USAGE_STAGING;
        desc.BindFlags = 0;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ.0 as u32;
        desc.MiscFlags = 0;
        let mut staging = None;
        // SAFETY: Staging descriptor mirrors source dimensions/format and requests CPU read access.
        unsafe { self.device.CreateTexture2D(&desc, None, Some(&mut staging)) }.map_err(backend)?;
        let staging = staging
            .ok_or_else(|| CaptureError::Backend("D3D11 returned no staging texture".into()))?;
        // SAFETY: Both resources use the same copied descriptor dimensions and pixel format.
        unsafe { self.context.CopyResource(&staging, &texture) };
        let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
        // SAFETY: The staging texture is created for CPU read and unmapped before return.
        unsafe {
            self.context
                .Map(&staging, 0, D3D11_MAP_READ, 0, Some(&mut mapped))
        }
        .map_err(backend)?;
        let result = copy_bgra_rows(&mapped, width, height).and_then(|rgba| {
            Frame::new(width, height, rgba).map_err(|e| CaptureError::Backend(e.to_string()))
        });
        // SAFETY: Map above succeeded for this resource and subresource.
        unsafe { self.context.Unmap(&staging, 0) };
        result
    }
}

fn needs_fresh_session(arrived: &Receiver<()>, seen_frame: bool) -> Result<bool, CaptureError> {
    match arrived.try_recv() {
        Ok(()) | Err(TryRecvError::Empty) => Ok(seen_frame),
        Err(TryRecvError::Disconnected) => Err(CaptureError::Backend(
            "WGC frame event channel closed".into(),
        )),
    }
}

fn qpc_now() -> Result<i64, CaptureError> {
    let mut ticks = 0;
    // SAFETY: QueryPerformanceCounter writes to a caller-owned i64.
    unsafe { QueryPerformanceCounter(&mut ticks) }.map_err(backend)?;
    if ticks <= 0 {
        return Err(CaptureError::Backend("invalid QPC timestamp".into()));
    }
    Ok(ticks)
}

fn newer_fresh_timestamp(
    timestamp_100ns: i64,
    newest_100ns: Option<i64>,
    cutoff_qpc: i64,
    now_qpc: i64,
    frequency: i64,
) -> bool {
    if timestamp_100ns <= 0 || cutoff_qpc <= 0 || now_qpc < cutoff_qpc || frequency <= 0 {
        return false;
    }
    // SystemRelativeTime is compositor-render QPC time, expressed as a TimeSpan
    // (100ns), not raw counter ticks or UTC. Cross-products avoid rounding the
    // cutoff down, rounding 'now' up, or overflowing i64 during conversion.
    // https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime
    let frame_time = i128::from(timestamp_100ns) * i128::from(frequency);
    frame_time >= i128::from(cutoff_qpc) * 10_000_000
        && frame_time <= i128::from(now_qpc) * 10_000_000
        && newest_100ns.is_none_or(|newest| timestamp_100ns > newest)
}

fn remaining_frame_wait(elapsed: Duration) -> Result<Duration, CaptureError> {
    FRAME_WAIT_TIMEOUT
        .checked_sub(elapsed)
        .filter(|remaining| !remaining.is_zero())
        .ok_or_else(|| CaptureError::Backend("timed out waiting for a fresh window frame".into()))
}

fn start_session(
    direct3d: &IDirect3DDevice,
    item: &GraphicsCaptureItem,
) -> Result<
    (
        Direct3D11CaptureFramePool,
        GraphicsCaptureSession,
        i64,
        Receiver<()>,
    ),
    CaptureError,
> {
    let size = item.Size().map_err(backend)?;
    if size.Width <= 0 || size.Height <= 0 {
        return Err(CaptureError::Backend("invalid WGC item size".into()));
    }
    let pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
        direct3d,
        DirectXPixelFormat::B8G8R8A8UIntNormalized,
        FRAME_POOL_BUFFERS,
        size,
    )
    .map_err(backend)?;
    let session = pool.CreateCaptureSession(item).map_err(backend)?;
    let (sender, arrived) = mpsc::sync_channel(1);
    let handler = TypedEventHandler::<Direct3D11CaptureFramePool, windows::core::IInspectable>::new(
        move |_, _| {
            let _ = sender.try_send(());
            Ok(())
        },
    );
    let frame_event = pool.FrameArrived(&handler).map_err(backend)?;
    if let Err(error) = session.StartCapture() {
        let _ = pool.RemoveFrameArrived(frame_event);
        return Err(backend(error));
    }
    Ok((pool, session, frame_event, arrived))
}

impl Drop for WindowsCapturer {
    fn drop(&mut self) {
        // Unsubscribe before field drop releases the pool. The session and pool
        // wrappers release themselves, and they are declared ahead of the device.
        let _ = self.pool.RemoveFrameArrived(self.frame_event);
    }
}

fn copy_bgra_rows(
    mapped: &D3D11_MAPPED_SUBRESOURCE,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, CaptureError> {
    let row_len = (width as usize)
        .checked_mul(4)
        .ok_or_else(|| CaptureError::Backend("frame row overflow".into()))?;
    let pitch = mapped.RowPitch as usize;
    let len = row_len
        .checked_mul(height as usize)
        .ok_or_else(|| CaptureError::Backend("frame length overflow".into()))?;
    if mapped.pData.is_null() || pitch < row_len || pitch.checked_mul(height as usize).is_none() {
        return Err(CaptureError::Backend("invalid mapped WGC surface".into()));
    }
    let mut rgba = vec![0u8; len];
    for y in 0..height as usize {
        // SAFETY: D3D11 Map guarantees RowPitch bytes per row for the mapped texture.
        let source = unsafe {
            std::slice::from_raw_parts((mapped.pData as *const u8).add(y * pitch), row_len)
        };
        let destination = &mut rgba[y * row_len..(y + 1) * row_len];
        for (src, dst) in source.chunks_exact(4).zip(destination.chunks_exact_mut(4)) {
            dst.copy_from_slice(&[src[2], src[1], src[0], src[3]]);
        }
    }
    Ok(rgba)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn desktop() -> RECT {
        RECT {
            left: -1000,
            top: -1000,
            right: 2000,
            bottom: 2000,
        }
    }

    fn table() -> SurfaceWindow {
        SurfaceWindow {
            hwnd: 10,
            process_id: 42,
            process_created_at_100ns: Some(100),
            owner: 0,
            root: 10,
            root_owner: 10,
            root_owner_process_id: 42,
            class: "UnityWndClass".into(),
            style: WS_POPUP.0,
            ex_style: 0,
            rect: RECT {
                left: 0,
                top: 0,
                right: 800,
                bottom: 600,
            },
        }
    }

    fn popup() -> SurfaceWindow {
        SurfaceWindow {
            hwnd: 20,
            owner: 10,
            root: 20,
            class: "tooltips_class32".into(),
            rect: RECT {
                left: 300,
                top: 200,
                right: 500,
                bottom: 400,
            },
            ..table()
        }
    }

    fn classify(above: &[SurfaceWindow], center: usize) -> Result<VisibleSurface, CaptureError> {
        let center_hit = above
            .iter()
            .find(|other| other.hwnd == center)
            .cloned()
            .unwrap_or_else(|| SurfaceWindow {
                hwnd: center,
                ..table()
            });
        classify_visible_surface(table(), above, &center_hit, &desktop(), 100)
    }

    #[test]
    fn empty_footprint_requires_three_successful_exact_zero_rectangles() {
        let zero = RECT::default();
        let proven = [Some(zero); 3];
        assert!(proven_empty_footprint(proven[0], proven[1], proven[2]));
        for query in 0..3 {
            let mut missing = proven;
            missing[query] = None;
            assert!(!proven_empty_footprint(missing[0], missing[1], missing[2]));
            for rect in [
                RECT {
                    left: 0,
                    top: 0,
                    right: 0,
                    bottom: 1,
                },
                RECT {
                    left: 0,
                    top: 0,
                    right: 1,
                    bottom: 0,
                },
                RECT {
                    left: 0,
                    top: 0,
                    right: 1,
                    bottom: 1,
                },
                RECT {
                    left: 1,
                    top: 1,
                    right: 1,
                    bottom: 1,
                },
                RECT {
                    left: 1,
                    top: 0,
                    right: 0,
                    bottom: 1,
                },
                RECT {
                    left: 0,
                    top: 1,
                    right: 1,
                    bottom: 0,
                },
            ] {
                let mut nonempty = proven;
                nonempty[query] = Some(rect);
                assert!(!proven_empty_footprint(
                    nonempty[0],
                    nonempty[1],
                    nonempty[2]
                ));
            }
        }
    }

    #[test]
    fn proven_empty_above_windows_are_skipped_without_ownership_or_class_whitelists() {
        let mut foreign = popup();
        foreign.owner = 0;
        foreign.process_id = 43;
        foreign.class = "UnrelatedZeroFootprintWindow".into();
        let mut owned = popup();
        owned.rect = RECT::default();
        assert!(owned_transient(&table(), &owned).is_some());
        for mut other in [foreign, owned] {
            other.rect = RECT::default();
            for proof in [
                [Some(RECT::default()); 3],
                [Some(RECT::default()), None, Some(RECT::default())],
            ] {
                let above = if proven_empty_footprint(proof[0], proof[1], proof[2]) {
                    Vec::new()
                } else {
                    vec![other.clone()]
                };
                if proof[1].is_some() {
                    let visible = classify(&above, 10).unwrap();
                    assert!(visible.popups.is_empty() && visible.occluded_regions.is_empty());
                } else {
                    assert!(classify(&above, 10).is_err());
                }
            }
        }
        let mut selected_zero = table();
        selected_zero.rect = RECT::default();
        assert!(matches!(
            classify_visible_surface(selected_zero.clone(), &[], &selected_zero, &desktop(), 100),
            Err(CaptureError::StaleWindow { .. })
        ));
        assert_eq!(
            classify(&[popup()], 20).unwrap().occluded_regions,
            [[300, 200, 500, 400]]
        );
    }

    #[test]
    fn surface_rejections_report_bounded_geometry_overlap_popup_and_center_causes() {
        let diagnostic = |result: Result<VisibleSurface, CaptureError>| match result {
            Err(CaptureError::Backend(message)) => {
                assert!(message.len() <= 1024);
                assert!(!message.contains(['\r', '\n', '\t']));
                for field in [
                    "offender=(hwnd=0x",
                    "pid=",
                    "class=",
                    "owner=0x",
                    "root=0x",
                    "rect=[",
                    "reference=(hwnd=0x",
                ] {
                    assert!(message.contains(field), "missing {field}: {message}");
                }
                message
            }
            other => panic!("expected a bounded surface diagnostic, got {other:?}"),
        };
        let mut unknown = popup();
        unknown.rect = RECT::default();
        unknown.class = "untrusted\r\n\t\"\\".repeat(1000);
        let message = diagnostic(classify(&[unknown], 10));
        assert!(message.contains("cause=nonpositive-geometry"));
        assert!(message.contains("hwnd=0x14 pid=42"));
        assert!(!message.contains(&"untrusted".repeat(100)));
        let mut one_pixel = popup();
        one_pixel.owner = 0;
        one_pixel.rect = RECT {
            left: 799,
            top: 10,
            right: 800,
            bottom: 11,
        };
        let message = diagnostic(classify(&[one_pixel.clone()], 10));
        assert!(message.contains("cause=foreign-overlap"));
        assert!(message.contains("rect=[799,10,800,11]"));
        one_pixel.rect.left = 800;
        one_pixel.rect.right = 801;
        assert!(classify(&[one_pixel], 10).is_ok());
        let mut outside = popup();
        outside.rect = RECT {
            left: 750,
            top: 100,
            right: 950,
            bottom: 300,
        };
        let mut blocker = popup();
        blocker.hwnd = 30;
        blocker.root = 30;
        blocker.owner = 0;
        blocker.rect = RECT {
            left: 850,
            top: 100,
            right: 851,
            bottom: 101,
        };
        let message = diagnostic(classify(&[blocker.clone(), outside.clone()], 10));
        assert!(message.contains("cause=popup-overlap"));
        assert!(message.contains("offender=(hwnd=0x1e"));
        assert!(message.contains("reference=(hwnd=0x14"));
        blocker.owner = 10;
        assert!(diagnostic(classify(&[blocker, outside], 10)).contains("cause=popup-overlap"));
        let mut wrong_hit = popup();
        wrong_hit.rect = RECT {
            left: 0,
            top: 0,
            right: 1,
            bottom: 1,
        };
        let message = diagnostic(classify(&[wrong_hit], 20));
        assert!(message.contains("cause=center-mismatch"));
        assert!(message.contains("offender=(hwnd=0x14 pid=42"));
    }

    #[test]
    fn selected_owned_popup_can_cover_center_but_keeps_original_desktop_occlusion() {
        let mut panel = popup();
        panel.rect.left = -100;
        let surface = classify(&[panel], 20).unwrap();
        assert_eq!(surface.popups[0].1.relative_bounds, [-100, 200, 500, 400]);
        assert_eq!(surface.occluded_regions, [[0, 200, 500, 400]]);
        assert_eq!(surface.selected.rect, table().rect);
        assert!(classify(&[popup()], 10).is_ok());
        assert!(classify(&[popup()], 999).is_err());
    }

    #[test]
    fn foreign_shared_executable_process_and_wrong_table_root_do_not_grant_exception() {
        let mut candidates = Vec::new();
        let mut foreign = popup();
        foreign.process_id = 43;
        candidates.push(foreign);
        let mut same_process_wrong_table = popup();
        same_process_wrong_table.owner = 30;
        candidates.push(same_process_wrong_table);
        let mut wrong_root = popup();
        wrong_root.root_owner = 30;
        candidates.push(wrong_root);
        let mut child_root = popup();
        child_root.root = 10;
        candidates.push(child_root);
        let mut wrong_owner_process = popup();
        wrong_owner_process.root_owner_process_id = 43;
        candidates.push(wrong_owner_process);
        for other in candidates {
            assert!(owned_transient(&table(), &other).is_none());
            assert!(classify(&[other], 10).is_err());
        }
    }

    #[test]
    fn popup_classification_requires_transient_style_not_application_or_table_class() {
        for class in ["", "UnityWndClass", "Chrome_WidgetWin_1", "arbitrary"] {
            let mut other = popup();
            other.class = class.into();
            assert!(classify(&[other], 10).is_err());
        }
        for style in [
            0,
            WS_CHILD.0 | WS_POPUP.0,
            WS_POPUP.0 | WS_CAPTION.0,
            WS_POPUP.0 | WS_SYSMENU.0,
            WS_POPUP.0 | WS_THICKFRAME.0,
        ] {
            let mut other = popup();
            other.style = style;
            assert!(classify(&[other], 10).is_err());
        }
        let mut other = popup();
        other.ex_style = WS_EX_APPWINDOW.0;
        assert!(classify(&[other], 10).is_err());
        let mut tool = popup();
        tool.class = "SelectedClientTransientTool".into();
        tool.ex_style = WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0;
        assert!(classify(&[tool], 20).is_ok());
    }

    #[test]
    fn owned_popup_bad_geometry_and_unknown_overlap_geometry_fail_closed() {
        for rect in [
            RECT {
                left: 300,
                top: 200,
                right: 300,
                bottom: 400,
            },
            RECT {
                left: 300,
                top: 400,
                right: 500,
                bottom: 200,
            },
            RECT {
                left: -1001,
                top: 200,
                right: 500,
                bottom: 400,
            },
            RECT {
                left: i32::MIN,
                top: 200,
                right: i32::MAX,
                bottom: 400,
            },
        ] {
            let mut other = popup();
            other.rect = rect;
            assert!(classify(&[other], 10).is_err());
        }
        let mut unknown = popup();
        unknown.owner = 0;
        unknown.rect = RECT::default();
        assert!(classify(&[unknown], 10).is_err());
    }

    #[test]
    fn full_outside_popup_visibility_rejects_intervening_foreign_or_owned_overlaps() {
        let mut outside = popup();
        outside.rect = RECT {
            left: 750,
            top: 100,
            right: 950,
            bottom: 300,
        };
        let surface = classify(&[outside.clone()], 10).unwrap();
        assert_eq!(surface.popups[0].1.relative_bounds, [750, 100, 950, 300]);
        assert_eq!(surface.occluded_regions, [[750, 100, 800, 300]]);
        let mut foreign = popup();
        foreign.hwnd = 30;
        foreign.owner = 0;
        foreign.rect = RECT {
            left: 850,
            top: 100,
            right: 900,
            bottom: 300,
        };
        assert!(classify(&[foreign, outside.clone()], 10).is_err());
        let mut second = outside.clone();
        second.hwnd = 30;
        second.root = 30;
        assert!(classify(&[second, outside], 10).is_err());
    }

    #[test]
    fn creation_time_and_capture_topology_are_fresh_witnesses_not_reusable_pid_proof() {
        for instance in [None, Some(0), Some(101)] {
            let mut other = popup();
            other.process_created_at_100ns = instance;
            assert!(classify(&[other], 10).is_err());
            let mut source = table();
            source.process_created_at_100ns = instance;
            assert!(
                classify_visible_surface(source.clone(), &[], &source, &desktop(), 100).is_err()
            );
        }
        let before = classify(&[popup()], 20).unwrap();
        let mut moved = popup();
        moved.rect.right += 1;
        let after = classify(&[moved], 20).unwrap();
        assert_ne!(
            before, after,
            "capture must reject changing popup geometry between copies"
        );
        assert_ne!(
            before,
            classify(&[], 10).unwrap(),
            "closure must not reuse the original mask"
        );
        let mut retitled_class = popup();
        retitled_class.class = "#32768".into();
        assert_ne!(before, classify(&[retitled_class], 20).unwrap());
        assert_eq!(unchanged_surface(&before, &before), Ok(true));
        assert_eq!(unchanged_surface(&before, &after), Ok(false));
        let mut changed_source = after;
        changed_source.selected.rect.left += 1;
        assert!(matches!(
            unchanged_surface(&before, &changed_source),
            Err(CaptureError::StaleWindow { .. })
        ));
    }

    #[test]
    fn popup_limit_is_bounded_and_center_hit_must_lie_inside_the_allowed_popup() {
        let windows: Vec<_> = (0..=MAX_OWNED_POPUPS)
            .map(|index| {
                let mut other = popup();
                other.hwnd += index;
                other.root = other.hwnd;
                other.rect = RECT {
                    left: index as i32 * 30,
                    top: 0,
                    right: index as i32 * 30 + 20,
                    bottom: 20,
                };
                other
            })
            .collect();
        assert!(classify(&windows[..MAX_OWNED_POPUPS], 10).is_ok());
        assert!(classify(&windows, 10).is_err());
        assert!(classify(&windows[..1], 20).is_err());
    }

    #[test]
    fn visible_capture_overlap_rejects_even_one_pixel_but_allows_adjacent_rectangles() {
        let source = RECT {
            left: -100,
            top: 20,
            right: 400,
            bottom: 520,
        };
        for other in [
            source,
            RECT {
                left: 399,
                top: 30,
                right: 450,
                bottom: 40,
            },
            RECT {
                left: -200,
                top: 0,
                right: -99,
                bottom: 21,
            },
        ] {
            assert!(rectangles_overlap(&source, &other));
        }
        for other in [
            RECT {
                left: 400,
                top: 20,
                right: 500,
                bottom: 520,
            },
            RECT {
                left: -100,
                top: 520,
                right: 400,
                bottom: 600,
            },
            RECT {
                left: -200,
                top: 20,
                right: -100,
                bottom: 520,
            },
        ] {
            assert!(!rectangles_overlap(&source, &other));
        }
    }

    #[test]
    fn idle_frame_pool_requests_a_new_session_without_blocking() {
        let (sender, arrived) = mpsc::sync_channel(1);
        assert_eq!(needs_fresh_session(&arrived, false), Ok(false));
        assert_eq!(needs_fresh_session(&arrived, true), Ok(true));
        sender.send(()).unwrap();
        assert_eq!(needs_fresh_session(&arrived, true), Ok(true));
        sender.send(()).unwrap();
        assert_eq!(needs_fresh_session(&arrived, false), Ok(false));
        drop(sender);
        assert!(matches!(
            needs_fresh_session(&arrived, true),
            Err(CaptureError::Backend(_))
        ));
    }

    #[test]
    fn timestamp_selection_rejects_stale_invalid_and_future_frames() {
        for timestamp in [i64::MIN, -1, 0, 99, 121, i64::MAX] {
            assert!(!newer_fresh_timestamp(
                timestamp, None, 100, 120, 10_000_000
            ));
        }
        for timestamp in [100, 110, 120] {
            assert!(newer_fresh_timestamp(timestamp, None, 100, 120, 10_000_000));
        }
    }

    #[test]
    fn timestamp_selection_keeps_newest_not_last_arrival() {
        for timestamps in [[99, 110, 120, 115], [120, 99, 110, 115], [110, 120, 0, 121]] {
            let mut newest = None;
            for timestamp in timestamps {
                if newer_fresh_timestamp(timestamp, newest, 100, 120, 10_000_000) {
                    newest = Some(timestamp);
                }
            }
            assert_eq!(newest, Some(120));
        }
        assert!(!newer_fresh_timestamp(120, Some(120), 100, 120, 10_000_000));
    }

    #[test]
    fn timestamp_selection_uses_qpc_frequency_without_unsafe_rounding() {
        // At 3Hz the cutoff is 3_333_333.333... units of 100ns. Do not
        // admit the preceding 100ns bin or a bin beyond the sampled 'now'.
        assert!(!newer_fresh_timestamp(3_333_333, None, 1, 2, 3));
        assert!(newer_fresh_timestamp(3_333_334, None, 1, 2, 3));
        assert!(newer_fresh_timestamp(6_666_666, None, 1, 2, 3));
        assert!(!newer_fresh_timestamp(6_666_667, None, 1, 2, 3));
    }

    #[test]
    fn timestamp_selection_fails_closed_on_invalid_or_reversed_clocks() {
        for (cutoff, now, frequency) in [
            (0, 120, 10_000_000),
            (-1, 120, 10_000_000),
            (100, 99, 10_000_000),
            (100, -1, 10_000_000),
            (100, 120, 0),
            (100, 120, -1),
        ] {
            assert!(!newer_fresh_timestamp(110, None, cutoff, now, frequency));
        }
    }

    #[test]
    fn timestamp_selection_widens_before_multiplying() {
        assert!(newer_fresh_timestamp(
            i64::MAX,
            None,
            i64::MAX - 1,
            i64::MAX,
            10_000_000,
        ));
        assert!(!newer_fresh_timestamp(
            i64::MAX,
            None,
            1,
            i64::MAX,
            i64::MAX
        ));
        assert!(newer_fresh_timestamp(
            10_000_000,
            None,
            i64::MAX,
            i64::MAX,
            i64::MAX
        ));
    }

    #[test]
    fn frame_wait_budget_has_a_strict_shared_deadline() {
        for elapsed_ms in [0, 1, 500, 1499] {
            assert_eq!(
                remaining_frame_wait(Duration::from_millis(elapsed_ms)),
                Ok(Duration::from_millis(1500 - elapsed_ms))
            );
        }
        for elapsed in [
            FRAME_WAIT_TIMEOUT,
            Duration::from_millis(1501),
            Duration::MAX,
        ] {
            assert!(remaining_frame_wait(elapsed).is_err());
        }
    }

    #[test]
    fn empty_pool_projection_uses_success_hresult() {
        // Exercise only the Rust projection, with no COM or WGC calls.
        let empty: windows::core::Result<Direct3D11CaptureFrame> =
            unsafe { windows::core::Type::from_abi(std::ptr::null_mut()) };
        assert_eq!(empty.unwrap_err().code(), S_OK);
    }

    /// Explicit local smoke: reads repeated frames into memory and prints dimensions only.
    #[test]
    #[ignore = "requires a user-selected live HWND in COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND"]
    fn visible_desktop_profile_intake() {
        use crate::recorder::{CaptureStamp, PrivateRecorder, RecorderConfig, RecorderStatus};
        use std::collections::hash_map::RandomState;
        use std::hash::BuildHasher;
        use std::io::Write;
        let configured = std::env::var("COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND")
            .expect("set COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND");
        let hwnd =
            usize::from_str_radix(configured.strip_prefix("0x").expect("0x-prefixed HWND"), 16)
                .unwrap();
        let origin = Instant::now();
        let window = discover()
            .unwrap()
            .windows
            .into_iter()
            .find(|window| window.hwnd == hwnd)
            .expect("selected HWND is visible in discovery");
        let instance = verify_visible_window(&window).unwrap();
        let source_utc = SystemTime::now();
        let captured_at_monotonic_ms = u64::try_from(origin.elapsed().as_millis()).unwrap();
        let frame = capture_visible_frame(&window, instance).unwrap();
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let mut recorder = PrivateRecorder::new(
            root,
            RecorderConfig {
                max_frames: 1,
                ..RecorderConfig::default()
            },
            SystemTime::now(),
        )
        .unwrap();
        recorder.record(
            &frame,
            CaptureStamp {
                source_utc,
                captured_at_monotonic_ms,
                generation: None,
                source_id: Some(RandomState::new().hash_one((window.process_id, window.hwnd))),
            },
        );
        assert_eq!(
            recorder.handle().snapshot().recording_status,
            RecorderStatus::CountLimit
        );
        let receipt = serde_json::json!({
            "event":"native_visible_profile_intake", "identity":window.identity(), "window":window,
            "frame":recorder.last_receipt(), "original_capture":recorder.original_capture(),
            "capture_directory":recorder.session_path(), "process_created_at_100ns":instance,
            "monotonic_clock_origin":"standalone_intake_test_process_local_Instant",
            "intake_process_id":std::process::id(), "occlusion_detection":"native_owned_top_level_only",
            "profile_qualified":false,
        });
        let mut manifest = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(recorder.session_path().join("intake.json"))
            .unwrap();
        manifest
            .write_all(&serde_json::to_vec(&receipt).unwrap())
            .unwrap();
        manifest.sync_all().unwrap();
        println!("NATIVE_VISIBLE_PROFILE_INTAKE={receipt}");
    }

    /// Explicit local smoke: reads repeated frames into memory and prints dimensions only.
    #[test]
    #[ignore = "requires a user-selected live HWND in COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND"]
    fn visible_desktop_capture_smoke() {
        let configured = std::env::var("COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND")
            .expect("set COINPOKER_VISIBLE_CAPTURE_SMOKE_HWND");
        let hwnd =
            usize::from_str_radix(configured.strip_prefix("0x").expect("0x-prefixed HWND"), 16)
                .unwrap();
        let window = discover()
            .unwrap()
            .windows
            .into_iter()
            .find(|window| window.hwnd == hwnd)
            .expect("selected HWND is visible in discovery");
        let instance = verify_visible_window(&window).unwrap();
        for index in 0..3 {
            let frame = capture_visible_frame(&window, instance).unwrap();
            frame.validate().unwrap();
            assert_eq!(
                frame.visibility.pixel_source,
                PixelSource::VisibleDesktopPixels
            );
            assert_eq!(
                frame.visibility.source_process_created_at_100ns,
                Some(instance)
            );
            println!("visible capture {index}: {}x{}, owned_popups={}, separate_popup_frames={}, occluded_regions={:?}",
                frame.width, frame.height, frame.visibility.owned_popups.len(), frame.popup_frames.len(), frame.visibility.occluded_regions);
        }
    }

    /// Explicit local WGC smoke: reads repeated frames into memory only.
    #[test]
    #[ignore = "requires a user-selected live HWND in COINPOKER_CAPTURE_SMOKE_HWND"]
    fn window_capture_smoke() {
        let configured = std::env::var("COINPOKER_CAPTURE_SMOKE_HWND")
            .expect("set COINPOKER_CAPTURE_SMOKE_HWND");
        let hwnd =
            usize::from_str_radix(configured.strip_prefix("0x").expect("0x-prefixed HWND"), 16)
                .unwrap();
        let window = discover()
            .unwrap()
            .windows
            .into_iter()
            .find(|window| window.hwnd == hwnd)
            .expect("selected HWND is visible in discovery");
        assert!(window.on_screen);
        let mut capturer = WindowsCapturer::for_window(&window).unwrap();
        for index in 0..5 {
            let started = std::time::Instant::now();
            let frame = capturer.capture().unwrap();
            frame.validate().unwrap();
            println!(
                "capture {index}: {}x{} RGBA8, {} bytes, {} ms",
                frame.width,
                frame.height,
                frame.rgba.len(),
                started.elapsed().as_millis()
            );
            std::thread::sleep(Duration::from_millis(200));
        }
    }
}
