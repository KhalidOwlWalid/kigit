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
// Code logs through spdlog's default logger (spdlog::info(...), ...).
#pragma once

#include <string>

namespace kigit::logging {

struct Options {
    bool enabled = true;      // write a log file
    std::string dir;          // folder for a new session file ("" = default)
    std::string file;         // append to this file instead of starting a new one
    bool console = false;     // also print log lines to stderr (-v, or for the GUI)
    bool debug = false;       // include debug lines
};

// The default log folder: $KIGIT_LOG_DIR, else platform::state_dir()/kigit/log.
std::string default_dir();

// Starts logging for this session. Returns the log file's path, or "" if
// there's none (disabled, or the folder can't be written; logging problems
// never stop kigit). Until this is called, logging goes nowhere.
std::string start(const Options& options, const std::string& name = "kigit");

// Flushes and closes the log.
void stop();

} // namespace kigit::logging
