#include "utils/platform.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <process.h>
#include <thread>
#include <windows.h>
#include <wincred.h>
#ifdef _MSC_VER
#pragma comment(lib, "advapi32.lib")
#endif
#else
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <thread>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
#endif

namespace fs = std::filesystem;

namespace kigit::platform {

namespace {

std::string env(const char* name) {
    const char* v = std::getenv(name);
    return v ? v : "";
}

} // namespace

#ifdef _WIN32

// Windows programs split their command line with the MSVCRT rules:
// backslashes are literal except before a quote.
std::string quote(const std::string& arg) {
    std::string out = "\"";
    size_t slashes = 0;
    for (char c : arg) {
        if (c == '\\') {
            ++slashes;
            continue;
        }
        if (c == '"') out.append(slashes * 2 + 1, '\\');
        else out.append(slashes, '\\');
        slashes = 0;
        out += c;
    }
    out.append(slashes * 2, '\\');
    return out + "\"";
}

const char* null_device() { return "NUL"; }

void binary_stdout() {
    std::fflush(stdout);
    _setmode(_fileno(stdout), _O_BINARY);
}

CommandResult run_shell(const std::string& command_line, bool keep_stderr) {
    // cmd.exe /c strips one pair of outer quotes, so wrap the whole line in
    // one; binary mode so nothing in git's output is translated.
    std::string cmd = "\"" + command_line + (keep_stderr ? "" : " 2>NUL") + "\"";
    CommandResult r;
    FILE* p = _popen(cmd.c_str(), "rb");
    if (!p) return r;
    std::array<char, 1 << 16> buf;
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), p)) > 0) r.out.append(buf.data(), n);
    r.code = _pclose(p);
    r.ok = r.code == 0;
    return r;
}

namespace {

std::wstring widen(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), w.data(), n);
    return w;
}

// Reads a pipe until it closes.
void drain(HANDLE h, std::string& out) {
    std::array<char, 1 << 16> buf;
    DWORD n = 0;
    while (ReadFile(h, buf.data(), static_cast<DWORD>(buf.size()), &n, nullptr) && n > 0) out.append(buf.data(), n);
}

RunResult run_impl(const std::vector<std::string>& args, bool capture_stderr, const std::string* input) {
    RunResult r;
    if (args.empty()) return r;
    std::optional<fs::path> exe = find_program(args[0]);
    std::string cmdline = quote(exe ? exe->string() : args[0]);
    for (size_t i = 1; i < args.size(); ++i) cmdline += " " + quote(args[i]);

    SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
    HANDLE out_r, out_w, err_r = nullptr, err_w, in, in_w = nullptr;
    if (!CreatePipe(&out_r, &out_w, &sa, 0)) return r;
    SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0);
    if (capture_stderr) {
        CreatePipe(&err_r, &err_w, &sa, 0);
        SetHandleInformation(err_r, HANDLE_FLAG_INHERIT, 0);
    } else {
        err_w = CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr);
    }
    if (input) {
        CreatePipe(&in, &in_w, &sa, 0);
        SetHandleInformation(in_w, HANDLE_FLAG_INHERIT, 0);
    } else {
        in = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ, &sa, OPEN_EXISTING, 0, nullptr);
    }

    STARTUPINFOW si{};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = in;
    si.hStdOutput = out_w;
    si.hStdError = err_w;
    PROCESS_INFORMATION pi{};
    std::wstring wcmd = widen(cmdline);
    BOOL started = CreateProcessW(nullptr, wcmd.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr,
                                  &si, &pi);
    CloseHandle(out_w);
    CloseHandle(err_w);
    CloseHandle(in);
    if (!started) {
        CloseHandle(out_r);
        if (err_r) CloseHandle(err_r);
        if (in_w) CloseHandle(in_w);
        return r;
    }
    // Write the input and read stderr on threads so no pipe can fill up and stall.
    std::thread writer;
    if (in_w) writer = std::thread([&] {
        DWORD n = 0;
        WriteFile(in_w, input->data(), static_cast<DWORD>(input->size()), &n, nullptr);
        CloseHandle(in_w);
    });
    std::thread err_reader;
    if (err_r) err_reader = std::thread([&] { drain(err_r, r.err); });
    drain(out_r, r.out);
    if (err_reader.joinable()) err_reader.join();
    if (writer.joinable()) writer.join();
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    CloseHandle(out_r);
    if (err_r) CloseHandle(err_r);
    r.code = static_cast<int>(code);
    r.ok = r.code == 0;
    return r;
}

} // namespace

bool stderr_supports_color() {
    // Windows Terminal and VS Code set these; the classic console may not show ANSI codes.
    return _isatty(_fileno(stderr)) && (!env("WT_SESSION").empty() || env("TERM_PROGRAM") == "vscode");
}

fs::path executable_path(const char* argv0) {
    std::wstring buf(MAX_PATH, L'\0');
    for (;;) {
        DWORD n = GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
        if (n == 0) return fs::absolute(argv0);
        if (n < buf.size()) return fs::path(buf.substr(0, n));
        buf.resize(buf.size() * 2);
    }
}

std::optional<fs::path> find_program(const std::string& name) {
    std::vector<std::string> exts = {""};
    std::string pathext = env("PATHEXT").empty() ? ".COM;.EXE;.BAT;.CMD" : env("PATHEXT");
    for (size_t start = 0; start <= pathext.size();) {
        size_t end = pathext.find(';', start);
        exts.push_back(pathext.substr(start, end == std::string::npos ? std::string::npos : end - start));
        if (end == std::string::npos) break;
        start = end + 1;
    }
    std::string path = env("PATH");
    for (size_t start = 0; start <= path.size();) {
        size_t end = path.find(';', start);
        fs::path dir = path.substr(start, end == std::string::npos ? std::string::npos : end - start);
        for (const auto& ext : exts) {
            std::error_code ec;
            fs::path cand = dir / (name + ext);
            if (!dir.empty() && fs::is_regular_file(cand, ec)) return cand;
        }
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return std::nullopt;
}

namespace {

// Ctrl+C reaches every process on the console. While a child (the GUI) runs,
// kigit lets it handle Ctrl+C and shut down, and just waits for it; dying
// first would leave the child running behind the prompt. A handler function,
// unlike SetConsoleCtrlHandler(nullptr, TRUE), isn't inherited by the child.
BOOL WINAPI let_child_handle_ctrl_c(DWORD type) { return type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT; }

} // namespace

int run_program(const fs::path& program, const std::vector<std::string>& args) {
    // Started directly, not through cmd.exe, so there's no extra process in between.
    std::string cmdline = quote(program.string());
    for (const auto& a : args) cmdline += " " + quote(a);
    std::wstring wcmd = widen(cmdline);
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    SetConsoleCtrlHandler(let_child_handle_ctrl_c, TRUE);
    if (!CreateProcessW(nullptr, wcmd.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr, &si, &pi)) {
        SetConsoleCtrlHandler(let_child_handle_ctrl_c, FALSE);
        std::fprintf(stderr, "kigit: failed to start %s (error %lu)\n", program.string().c_str(), GetLastError());
        return 127;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    SetConsoleCtrlHandler(let_child_handle_ctrl_c, FALSE);
    return static_cast<int>(code);
}

bool open_in_browser(const fs::path& file) {
    return std::system(("start \"\" " + quote(file.string())).c_str()) == 0;
}

void set_env(const std::string& name, const std::string& value) { _putenv_s(name.c_str(), value.c_str()); }

int process_id() { return _getpid(); }

std::tm local_time(std::time_t t) {
    std::tm out{};
    localtime_s(&out, &t);
    return out;
}

fs::path home_dir() {
    if (!env("USERPROFILE").empty()) return env("USERPROFILE");
    return env("HOMEDRIVE") + env("HOMEPATH");
}

fs::path state_dir() {
    if (!env("LOCALAPPDATA").empty()) return env("LOCALAPPDATA");
    return home_dir() / "AppData" / "Local";
}

#else // Linux, macOS

std::string quote(const std::string& arg) {
    std::string out = "'";
    for (char c : arg) {
        if (c == '\'') out += "'\\''";
        else out += c;
    }
    return out + "'";
}

const char* null_device() { return "/dev/null"; }

void binary_stdout() {}

CommandResult run_shell(const std::string& command_line, bool keep_stderr) {
    CommandResult r;
    FILE* p = popen((command_line + (keep_stderr ? "" : " 2>/dev/null")).c_str(), "r");
    if (!p) return r;
    std::array<char, 1 << 16> buf;
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), p)) > 0) r.out.append(buf.data(), n);
    int status = pclose(p);
    r.code = (status != -1 && WIFEXITED(status)) ? WEXITSTATUS(status) : -1;
    r.ok = r.code == 0;
    return r;
}

namespace {

RunResult run_impl(const std::vector<std::string>& args, bool capture_stderr, const std::string* input) {
    RunResult r;
    if (args.empty()) return r;
    int out_pipe[2], err_pipe[2] = {-1, -1}, in_pipe[2] = {-1, -1};
    if (pipe(out_pipe) != 0) return r;
    if (capture_stderr && pipe(err_pipe) != 0) {
        close(out_pipe[0]);
        close(out_pipe[1]);
        return r;
    }
    if (input) {
        // A program that exits without reading all its input would otherwise
        // kill kigit with SIGPIPE; the write just fails instead.
        std::signal(SIGPIPE, SIG_IGN);
        if (pipe(in_pipe) != 0) {
            close(out_pipe[0]);
            close(out_pipe[1]);
            if (capture_stderr) close(err_pipe[0]), close(err_pipe[1]);
            return r;
        }
    }
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    if (input) {
        posix_spawn_file_actions_adddup2(&fa, in_pipe[0], 0);
        posix_spawn_file_actions_addclose(&fa, in_pipe[0]);
        posix_spawn_file_actions_addclose(&fa, in_pipe[1]);
    } else {
        posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
    }
    posix_spawn_file_actions_adddup2(&fa, out_pipe[1], 1);
    if (capture_stderr) posix_spawn_file_actions_adddup2(&fa, err_pipe[1], 2);
    else posix_spawn_file_actions_addopen(&fa, 2, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addclose(&fa, out_pipe[0]);
    if (capture_stderr) posix_spawn_file_actions_addclose(&fa, err_pipe[0]);

    std::vector<std::string> copy = args;
    std::vector<char*> argv;
    for (auto& a : copy) argv.push_back(a.data());
    argv.push_back(nullptr);
    pid_t pid;
    int rc = posix_spawnp(&pid, argv[0], &fa, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&fa);
    close(out_pipe[1]);
    if (capture_stderr) close(err_pipe[1]);
    if (input) close(in_pipe[0]);
    if (rc != 0) {
        close(out_pipe[0]);
        if (capture_stderr) close(err_pipe[0]);
        if (input) close(in_pipe[1]);
        return r;
    }
    std::thread writer;
    if (input) writer = std::thread([&] {
        size_t done = 0;
        while (done < input->size()) {
            ssize_t n = write(in_pipe[1], input->data() + done, input->size() - done);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            done += static_cast<size_t>(n);
        }
        close(in_pipe[1]);
    });
    // Read both pipes as data arrives, so neither can fill up and stall the child.
    std::vector<pollfd> fds = {{out_pipe[0], POLLIN, 0}};
    if (capture_stderr) fds.push_back({err_pipe[0], POLLIN, 0});
    std::array<char, 1 << 16> buf;
    size_t open_fds = fds.size();
    while (open_fds > 0) {
        if (poll(fds.data(), fds.size(), -1) < 0) {
            if (errno == EINTR) continue;
            break;
        }
        for (size_t i = 0; i < fds.size(); ++i) {
            if (fds[i].fd < 0 || !(fds[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            ssize_t n = read(fds[i].fd, buf.data(), buf.size());
            if (n > 0) {
                (i == 0 ? r.out : r.err).append(buf.data(), static_cast<size_t>(n));
            } else {
                close(fds[i].fd);
                fds[i].fd = -1;
                --open_fds;
            }
        }
    }
    if (writer.joinable()) writer.join();
    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
    }
    r.code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    r.ok = r.code == 0;
    return r;
}

} // namespace

bool stderr_supports_color() { return isatty(2) && env("TERM") != "dumb"; }

fs::path executable_path(const char* argv0) {
#ifdef __APPLE__
    uint32_t size = 0;
    _NSGetExecutablePath(nullptr, &size);
    std::string buf(size, '\0');
    if (_NSGetExecutablePath(buf.data(), &size) == 0) {
        std::error_code ec;
        fs::path p = fs::canonical(buf.c_str(), ec);
        if (!ec) return p;
    }
#else
    std::error_code ec;
    fs::path p = fs::read_symlink("/proc/self/exe", ec);
    if (!ec) return p;
#endif
    return fs::absolute(argv0);
}

std::optional<fs::path> find_program(const std::string& name) {
    std::string path = env("PATH");
    for (size_t start = 0; start <= path.size();) {
        size_t end = path.find(':', start);
        fs::path cand = fs::path(path.substr(start, end == std::string::npos ? std::string::npos : end - start)) / name;
        if (::access(cand.c_str(), X_OK) == 0) return cand;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return std::nullopt;
}

int run_program(const fs::path& program, const std::vector<std::string>& args) {
    std::vector<std::string> all = {program.string()};
    all.insert(all.end(), args.begin(), args.end());
    std::vector<char*> argv;
    for (auto& a : all) argv.push_back(a.data());
    argv.push_back(nullptr);
    ::execv(program.c_str(), argv.data());
    std::perror("kigit: failed to start program");
    return 127;
}

bool open_in_browser(const fs::path& file) {
#ifdef __APPLE__
    std::string cmd = "open " + quote(file.string()) + " >/dev/null 2>&1 &";
#else
    std::string cmd = "xdg-open " + quote(file.string()) + " >/dev/null 2>&1 &";
#endif
    return std::system(cmd.c_str()) == 0;
}

void set_env(const std::string& name, const std::string& value) { ::setenv(name.c_str(), value.c_str(), 1); }

int process_id() { return static_cast<int>(::getpid()); }

std::tm local_time(std::time_t t) {
    std::tm out{};
    localtime_r(&t, &out);
    return out;
}

fs::path home_dir() { return env("HOME").empty() ? fs::path("/tmp") : fs::path(env("HOME")); }

fs::path state_dir() {
#ifdef __APPLE__
    return home_dir() / "Library" / "Application Support";
#else
    if (!env("XDG_STATE_HOME").empty()) return env("XDG_STATE_HOME");
    return home_dir() / ".local" / "state";
#endif
}

#endif

RunResult run(const std::vector<std::string>& args, bool capture_stderr) {
    return run_impl(args, capture_stderr, nullptr);
}

RunResult run_input(const std::vector<std::string>& args, const std::string& input, bool capture_stderr) {
    return run_impl(args, capture_stderr, &input);
}

std::time_t file_time(const fs::path& p) {
    // file_time_type's clock differs per platform; convert via "now" on both clocks.
    std::error_code ec;
    auto ft = fs::last_write_time(p, ec);
    if (ec) return 0;
    auto sys = std::chrono::system_clock::now() +
               std::chrono::duration_cast<std::chrono::system_clock::duration>(ft - fs::file_time_type::clock::now());
    return std::chrono::system_clock::to_time_t(sys);
}

std::optional<fs::path> find_kicad_cli() {
    std::error_code ec;
    if (std::string set = env("KIGIT_KICAD_CLI"); !set.empty())
        return fs::is_regular_file(set, ec) ? std::optional<fs::path>(set) : std::nullopt;
    if (auto found = find_program("kicad-cli")) return found;
    // Where the KiCad installers put it, newest version first.
    std::vector<fs::path> spots;
#ifdef _WIN32
    for (const char* var : {"ProgramFiles", "ProgramW6432", "LOCALAPPDATA"}) {
        fs::path base = env(var);
        if (base.empty()) continue;
        fs::path kicad = std::string(var) == "LOCALAPPDATA" ? base / "Programs" / "KiCad" : base / "KiCad";
        std::vector<fs::path> versions;
        for (const auto& e : fs::directory_iterator(kicad, ec)) versions.push_back(e.path());
        // By number, newest first: as text "8.0" would come before "10.0".
        auto number = [](const fs::path& p) { return std::strtod(p.filename().string().c_str(), nullptr); };
        std::sort(versions.begin(), versions.end(),
                  [&](const fs::path& a, const fs::path& b) { return number(a) > number(b); });
        for (const auto& v : versions) spots.push_back(v / "bin" / "kicad-cli.exe");
    }
#elif defined(__APPLE__)
    spots.push_back("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli");
#else
    spots = {"/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"};
#endif
    for (const auto& p : spots)
        if (fs::is_regular_file(p, ec)) return p;
    return std::nullopt;
}

// ------------------------------------------------------------------ keyring
// Secrets are named "kigit:<name>" (Windows) or found by the attributes
// service=kigit name=<name> (Secret Service).

#if defined(_WIN32)

Keyring keyring() {
    static const Keyring k = [] {
        Keyring r;
        if (env("KIGIT_KEYRING") == "off") { r.why = "turned off (KIGIT_KEYRING=off)"; return r; }
        r.available = true;
        r.name = "Windows Credential Manager";
        return r;
    }();
    return k;
}

std::optional<std::string> secret_get(const std::string& name) {
    if (!keyring().available) return std::nullopt;
    PCREDENTIALW cred = nullptr;
    if (!CredReadW(widen("kigit:" + name).c_str(), CRED_TYPE_GENERIC, 0, &cred)) return std::nullopt;
    std::string value(reinterpret_cast<const char*>(cred->CredentialBlob), cred->CredentialBlobSize);
    SecureZeroMemory(cred->CredentialBlob, cred->CredentialBlobSize);
    CredFree(cred);
    return value;
}

bool secret_set(const std::string& name, const std::string& label, const std::string& value) {
    if (!keyring().available) return false;
    std::wstring target = widen("kigit:" + name), comment = widen(label), user = L"kigit";
    std::string blob = value;
    CREDENTIALW cred{};
    cred.Type = CRED_TYPE_GENERIC;
    cred.TargetName = target.data();
    cred.Comment = comment.data();
    cred.UserName = user.data();
    cred.CredentialBlobSize = static_cast<DWORD>(blob.size());
    cred.CredentialBlob = reinterpret_cast<LPBYTE>(blob.data());
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE;
    bool ok = CredWriteW(&cred, 0) != FALSE;
    SecureZeroMemory(blob.data(), blob.size());
    return ok;
}

bool secret_delete(const std::string& name) {
    if (!keyring().available) return false;
    return CredDeleteW(widen("kigit:" + name).c_str(), CRED_TYPE_GENERIC, 0) != FALSE || GetLastError() == ERROR_NOT_FOUND;
}

#elif defined(__APPLE__)

Keyring keyring() { return {false, "", "the macOS Keychain isn't supported yet"}; }
std::optional<std::string> secret_get(const std::string&) { return std::nullopt; }
bool secret_set(const std::string&, const std::string&, const std::string&) { return false; }
bool secret_delete(const std::string&) { return false; }

#else

namespace {

std::string secret_tool() {
    if (std::string set = env("KIGIT_SECRET_TOOL"); !set.empty()) return set;
    auto found = find_program("secret-tool");
    return found ? found->string() : "";
}

std::string first_line(std::string s) {
    s = s.substr(0, s.find('\n'));
    while (!s.empty() && (s.back() == '\r' || s.back() == ' ')) s.pop_back();
    return s;
}

} // namespace

Keyring keyring() {
    static const Keyring k = [] {
        Keyring r;
        if (env("KIGIT_KEYRING") == "off") { r.why = "turned off (KIGIT_KEYRING=off)"; return r; }
        std::string tool = secret_tool();
        if (tool.empty()) {
            r.why = "no secret-tool program (install libsecret-tools, or your distribution's libsecret package)";
            return r;
        }
        // Asking for something that isn't there: no output and exit 1 means it answered.
        RunResult probe = run({tool, "lookup", "service", "kigit", "name", "kigit-probe"}, true);
        if (probe.code == 0 || (probe.code == 1 && first_line(probe.err).empty())) {
            r.available = true;
            r.name = "your login keyring (Secret Service)";
        } else {
            r.why = "no keyring answered" + (first_line(probe.err).empty() ? std::string() : ": " + first_line(probe.err));
        }
        return r;
    }();
    return k;
}

std::optional<std::string> secret_get(const std::string& name) {
    if (!keyring().available) return std::nullopt;
    RunResult r = run({secret_tool(), "lookup", "service", "kigit", "name", name}, true);
    if (r.code != 0 || r.out.empty()) return std::nullopt;
    if (r.out.back() == '\n') r.out.pop_back();
    return r.out;
}

bool secret_set(const std::string& name, const std::string& label, const std::string& value) {
    if (!keyring().available) return false;
    // The secret goes on stdin: never on a command line.
    return run_input({secret_tool(), "store", "--label=" + label, "service", "kigit", "name", name}, value, true).code == 0;
}

bool secret_delete(const std::string& name) {
    if (!keyring().available) return false;
    run({secret_tool(), "clear", "service", "kigit", "name", name}, true);
    return true;
}

#endif

} // namespace kigit::platform
