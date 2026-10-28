#include "platform.hpp"

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <process.h>
#include <thread>
#include <windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <poll.h>
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

} // namespace

RunResult run(const std::vector<std::string>& args, bool capture_stderr) {
    RunResult r;
    if (args.empty()) return r;
    std::optional<fs::path> exe = find_program(args[0]);
    std::string cmdline = quote(exe ? exe->string() : args[0]);
    for (size_t i = 1; i < args.size(); ++i) cmdline += " " + quote(args[i]);

    SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
    HANDLE out_r, out_w, err_r = nullptr, err_w;
    if (!CreatePipe(&out_r, &out_w, &sa, 0)) return r;
    SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0);
    if (capture_stderr) {
        CreatePipe(&err_r, &err_w, &sa, 0);
        SetHandleInformation(err_r, HANDLE_FLAG_INHERIT, 0);
    } else {
        err_w = CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr);
    }
    HANDLE in = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ, &sa, OPEN_EXISTING, 0, nullptr);

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
        return r;
    }
    // Read stderr on a thread so neither pipe can fill up and stall git.
    std::thread err_reader;
    if (err_r) err_reader = std::thread([&] { drain(err_r, r.err); });
    drain(out_r, r.out);
    if (err_reader.joinable()) err_reader.join();
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

RunResult run(const std::vector<std::string>& args, bool capture_stderr) {
    RunResult r;
    if (args.empty()) return r;
    int out_pipe[2], err_pipe[2] = {-1, -1};
    if (pipe(out_pipe) != 0) return r;
    if (capture_stderr && pipe(err_pipe) != 0) {
        close(out_pipe[0]);
        close(out_pipe[1]);
        return r;
    }
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
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
    if (rc != 0) {
        close(out_pipe[0]);
        if (capture_stderr) close(err_pipe[0]);
        return r;
    }
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
    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
    }
    r.code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    r.ok = r.code == 0;
    return r;
}

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

std::time_t file_time(const fs::path& p) {
    // file_time_type's clock differs per platform; convert via "now" on both clocks.
    std::error_code ec;
    auto ft = fs::last_write_time(p, ec);
    if (ec) return 0;
    auto sys = std::chrono::system_clock::now() +
               std::chrono::duration_cast<std::chrono::system_clock::duration>(ft - fs::file_time_type::clock::now());
    return std::chrono::system_clock::to_time_t(sys);
}

} // namespace kigit::platform
