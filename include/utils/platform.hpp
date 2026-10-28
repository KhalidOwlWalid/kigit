// Everything that differs between Windows, Linux and macOS lives here, so the
// rest of kigit never touches OS APIs directly.
#pragma once

#include <ctime>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace kigit::platform {

struct CommandResult {
    bool ok = false; // ran and exited with 0
    int code = -1;   // exit code
    std::string out; // standard output (binary-safe)
};

// Runs a program directly (no shell, so arguments are passed exactly as
// given; nothing is expanded or re-quoted) and captures its standard
// output. args[0] is the program, found on PATH. stderr is captured into
// `err` if `capture_stderr`, else discarded.
struct RunResult : CommandResult {
    std::string err;
};
RunResult run(const std::vector<std::string>& args, bool capture_stderr = false);

// Runs a command line through the system shell (sh, or cmd.exe on Windows)
// and captures its standard output. Unless `keep_stderr`, stderr is thrown
// away. Build the command with quote() for each argument. Prefer run(args).
CommandResult run_shell(const std::string& command_line, bool keep_stderr = false);

// One argument, quoted for this platform's shell.
std::string quote(const std::string& arg);

// Makes stdout binary (Windows would otherwise turn "\n" into "\r\n"),
// for output other programs read (-o -). Does nothing elsewhere.
void binary_stdout();

// "/dev/null", or "NUL" on Windows.
const char* null_device();

// True if stderr is a terminal that shows ANSI colours.
bool stderr_supports_color();

// This executable's own path (argv0 is the fallback).
std::filesystem::path executable_path(const char* argv0);

// Full path of a program on PATH (on Windows, trying PATHEXT: .exe, .cmd, ...).
std::optional<std::filesystem::path> find_program(const std::string& name);

// Runs a program with arguments, sharing this process's console, and returns
// its exit code. On Linux/macOS it replaces this process (and only returns
// if starting it failed).
int run_program(const std::filesystem::path& program, const std::vector<std::string>& args);

// Opens a file in the default browser, without waiting.
bool open_in_browser(const std::filesystem::path& file);

void set_env(const std::string& name, const std::string& value);
int process_id();
std::tm local_time(std::time_t t);

// The user's home folder (HOME, or USERPROFILE on Windows).
std::filesystem::path home_dir();

// Where apps keep their own data: ~/.local/state (Linux),
// ~/Library/Application Support (macOS), %LOCALAPPDATA% (Windows).
std::filesystem::path state_dir();

// A file's modification time as a time_t.
std::time_t file_time(const std::filesystem::path& p);

} // namespace kigit::platform
