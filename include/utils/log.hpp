// Session logging (spdlog).
//
// Each kigit run is a session with its own log file, named after when it
// started (kigit_2026-10-28_14-03-12_12345.log), in the log folder:
//   --log-dir DIR, else $KIGIT_LOG_DIR, else <app data>/kigit/log
//   (~/.local/state on Linux, ~/Library/Application Support on macOS,
//   %LOCALAPPDATA% on Windows)
// The GUI passes --log-file so its session and every kigit call it makes
// share one file. Old logs are kept.
//
// Levels, each for the file and the console (stderr) on its own:
//   --log-level LEVEL      the file's (default debug, so a log sent in
//                          for a problem has everything; $KIGIT_LOG_LEVEL)
//   --console-level LEVEL  stderr's (default off; $KIGIT_CONSOLE_LEVEL)
//   --log-stderr           = --console-level info; -V = --console-level debug
// LEVEL: debug, info, warning, error or off.
//
// What goes at which level:
//   debug    the steps of a run: commands run (git, curl, kicad-cli) and how
//            they ended, files read, counts, cache hits, HTTP status codes
//   info     what a run did: its command, results in a line, files written
//   warning  something the user should know or act on (also printed for them)
//   error    the run failed
// Never log secrets (API keys, tokens): log that one is set, not what it is.
//
// Code logs through spdlog's default logger (spdlog::info(...), ...).
#pragma once

#include <string>

namespace kigit::logging {

struct Options {
    bool enabled = true;                // write a log file
    std::string dir;                    // folder for a new session file ("" = default)
    std::string file;                   // append to this file instead of starting a new one
    std::string file_level = "debug";   // lowest level written to the file
    std::string console_level = "off";  // lowest level printed to stderr
};

// The default log folder: $KIGIT_LOG_DIR, else platform::state_dir()/kigit/log.
std::string default_dir();

// The logging options in argv (after $KIGIT_LOG_LEVEL / $KIGIT_CONSOLE_LEVEL).
// Throws std::invalid_argument for an unknown level.
Options from_args(int argc, char** argv);

// For option parsers: 1 if `arg` is a logging flag that takes a value
// (--log-dir DIR), 0 if it takes none (--no-log), -1 if it's not one.
int flag_arity(const std::string& arg);

// "debug", "info", "warning" (or "warn"), "error", "off": true if known.
bool valid_level(const std::string& level);

// Starts logging for this session. Returns the log file's path, or "" if
// there's none (disabled, or the folder can't be written; logging problems
// never stop kigit). Until this is called, logging goes nowhere.
std::string start(const Options& options, const std::string& name = "kigit");

// Flushes and closes the log.
void stop();

} // namespace kigit::logging
