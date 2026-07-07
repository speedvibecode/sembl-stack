// npm cannot build @vscode/windows-ca-certs on this box: its binding.gyp demands
// Spectre-mitigated MSVC libraries (error MSB8040), a VS installer component that
// isn't present. Theia's backend bundler (@theia/bundle-plugin) hard-resolves the
// module's build/Release/crypt32.node on win32, so a missing module fails the whole
// `theia build`. A copy built once with SpectreMitigation=false is vendored under
// vendor/windows-ca-certs; this postinstall copies it into node_modules whenever a
// (re)install left it missing. No-op on non-Windows and when already present.
const fs = require('fs');
const path = require('path');

if (process.platform !== 'win32') {
    process.exit(0);
}
const src = path.join(__dirname, '..', 'vendor', 'windows-ca-certs');
const dst = path.join(__dirname, '..', 'node_modules', '@vscode', 'windows-ca-certs');
if (!fs.existsSync(path.join(dst, 'build', 'Release', 'crypt32.node'))) {
    fs.cpSync(src, dst, { recursive: true });
    console.log('vendored @vscode/windows-ca-certs -> node_modules (see ide/scripts/install-windows-ca-certs.js)');
}
