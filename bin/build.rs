// The `screencapturekit` dependency (pulled in through `ingest`) links a
// Swift bridge that loads `@rpath/libswift_Concurrency.dylib` at runtime.
// Its build script emits rpath link args, but `cargo:rustc-link-arg` from a
// dependency only applies to that dependency's own targets, so the rpath
// must be baked in here for this package's binaries and tests to load on
// hosts where the Swift concurrency runtime ships only inside the Xcode
// toolchain.

use std::env;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-env-changed=DEVELOPER_DIR");

    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("macos") {
        return;
    }

    println!("cargo:rustc-link-arg=-Wl,-rpath,/usr/lib/swift");

    match Command::new("xcode-select").arg("-p").output() {
        Ok(output) if output.status.success() => {
            let xcode_path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            println!(
                "cargo:rustc-link-arg=-Wl,-rpath,{xcode_path}/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift-5.5/macosx"
            );
            println!(
                "cargo:rustc-link-arg=-Wl,-rpath,{xcode_path}/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift/macosx"
            );
        }
        Ok(output) => {
            println!(
                "cargo:warning=`xcode-select -p` failed (status={:?}); Swift runtime rpaths were not baked in",
                output.status.code()
            );
        }
        Err(err) => {
            println!(
                "cargo:warning=`xcode-select` could not be invoked ({err}); Swift runtime rpaths were not baked in"
            );
        }
    }
}
