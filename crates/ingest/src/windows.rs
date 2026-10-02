//! Win32 discovery and Windows Graphics Capture for a single HWND.

use std::collections::HashMap;
use std::ffi::c_void;
use std::mem::size_of;
use std::path::Path;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

use windows::core::{factory, Interface, BOOL, PWSTR};
use windows::Foundation::TypedEventHandler;
use windows::Graphics::Capture::{
    Direct3D11CaptureFrame, Direct3D11CaptureFramePool, GraphicsCaptureItem, GraphicsCaptureSession,
};
use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
use windows::Graphics::DirectX::DirectXPixelFormat;
use windows::Win32::Foundation::{
    CloseHandle, E_ACCESSDENIED, HANDLE, HMODULE, HWND, LPARAM, RECT,
};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, ID3D11Texture2D, D3D11_CPU_ACCESS_READ,
    D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_MAPPED_SUBRESOURCE, D3D11_MAP_READ, D3D11_SDK_VERSION,
    D3D11_TEXTURE2D_DESC, D3D11_USAGE_STAGING,
};
use windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM;
use windows::Win32::Graphics::Dxgi::IDXGIDevice;
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::SystemInformation::OSVERSIONINFOW;
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::System::WinRT::Direct3D11::{
    CreateDirect3D11DeviceFromDXGIDevice, IDirect3DDxgiInterfaceAccess,
};
use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;
use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindowRect, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId,
    IsIconic, IsWindow, IsWindowVisible,
};

use crate::capture::{CaptureError, DiscoverySnapshot, Frame, WindowInfo};
use crate::discovery::ApplicationInfo;

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
    let on_screen = unsafe { IsWindowVisible(hwnd).as_bool() && !IsIconic(hwnd).as_bool() };
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

fn verify_window(selected: &WindowInfo) -> Result<(), CaptureError> {
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
        verify_window(&self.selected)?;
        if self.seen_frame {
            if needs_fresh_session(&self.arrived)? {
                // WGC is change-driven: a static window often sends no second
                // frame. A fresh session/pool produces a new snapshot without
                // reusing old pixels as another independent observation.
                self.restart_session()?;
                self.wait_for_frame()?;
            }
        } else {
            self.wait_for_frame()?;
        }
        let captured = self.pool.TryGetNextFrame().map_err(backend)?;
        let result = self.copy_frame(&captured);
        let _ = captured.Close();
        let frame = result?;
        verify_window(&self.selected)?;
        self.seen_frame = true;
        Ok(frame)
    }

    fn wait_for_frame(&self) -> Result<(), CaptureError> {
        self.arrived
            .recv_timeout(Duration::from_millis(1500))
            .map_err(|_| CaptureError::Backend("timed out waiting for a new window frame".into()))
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

fn needs_fresh_session(arrived: &Receiver<()>) -> Result<bool, CaptureError> {
    match arrived.try_recv() {
        Ok(()) => Ok(false),
        Err(TryRecvError::Empty) => Ok(true),
        Err(TryRecvError::Disconnected) => Err(CaptureError::Backend(
            "WGC frame event channel closed".into(),
        )),
    }
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
        2,
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

    #[test]
    fn idle_frame_pool_requests_a_new_session_without_blocking() {
        let (sender, arrived) = mpsc::sync_channel(1);
        assert_eq!(needs_fresh_session(&arrived), Ok(true));
        sender.send(()).unwrap();
        assert_eq!(needs_fresh_session(&arrived), Ok(false));
        drop(sender);
        assert!(matches!(
            needs_fresh_session(&arrived),
            Err(CaptureError::Backend(_))
        ));
    }

    /// Explicit local smoke: reads repeated frames into memory and prints dimensions only.
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
