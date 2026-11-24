#include "utils/log.hpp"

#include "utils/platform.hpp"

#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/sinks/null_sink.h>
#include <spdlog/sinks/stdout_sinks.h>
#include <spdlog/spdlog.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <stdexcept>

namespace fs = std::filesystem;

namespace kigit::logging {

namespace {

// Same layout as the GUI's Python log lines, so one file reads as one log.
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%n] [%l] %v";

// Quiet until start(): spdlog's built-in default logger prints to stdout,
// which would corrupt `-o -` output.
struct Silence {
    Silence() { spdlog::set_default_logger(std::make_shared<spdlog::logger>("kigit", std::make_shared<spdlog::sinks::null_sink_mt>())); }
} silence;

std::string session_file_name(const std::string& name) {
    std::tm now = platform::local_time(std::time(nullptr));
    char stamp[32];
    std::strftime(stamp, sizeof stamp, "%Y-%m-%d_%H-%M-%S", &now);
    return name + "_" + stamp + "_" + std::to_string(platform::process_id()) + ".log";
}

spdlog::level::level_enum level_of(const std::string& name) {
    if (name == "debug") return spdlog::level::debug;
    if (name == "info") return spdlog::level::info;
    if (name == "warning" || name == "warn") return spdlog::level::warn;
    if (name == "error") return spdlog::level::err;
    if (name == "off") return spdlog::level::off;
    throw std::invalid_argument("unknown log level '" + name + "' (debug, info, warning, error or off)");
}

} // namespace

bool valid_level(const std::string& level) {
    try {
        level_of(level);
        return true;
    } catch (const std::invalid_argument&) {
        return false;
    }
}

int flag_arity(const std::string& a) {
    if (a == "--log-dir" || a == "--log-file" || a == "--log-level" || a == "--console-level") return 1;
    if (a == "--no-log" || a == "--log-stderr" || a == "-V" || a == "--verbose") return 0;
    return -1;
}

Options from_args(int argc, char** argv) {
    Options o;
    if (const char* env = std::getenv("KIGIT_LOG_LEVEL"); env && *env) o.file_level = env;
    if (const char* env = std::getenv("KIGIT_CONSOLE_LEVEL"); env && *env) o.console_level = env;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        bool more = i + 1 < argc;
        if (a == "--no-log") o.enabled = false;
        else if (a == "--log-stderr") o.console_level = "info";
        else if (a == "-V" || a == "--verbose") o.console_level = "debug";
        else if (a == "--log-dir" && more) o.dir = argv[++i];
        else if (a == "--log-file" && more) o.file = argv[++i];
        else if (a == "--log-level" && more) o.file_level = argv[++i];
        else if (a == "--console-level" && more) o.console_level = argv[++i];
    }
    level_of(o.file_level); // throws if unknown
    level_of(o.console_level);
    return o;
}

std::string default_dir() {
    if (const char* env = std::getenv("KIGIT_LOG_DIR"); env && *env) return env;
    return (platform::state_dir() / "kigit" / "log").string();
}

std::string start(const Options& o, const std::string& name) {
    std::vector<spdlog::sink_ptr> sinks;
    std::string path;
    if (o.enabled) {
        try {
            fs::path p = !o.file.empty() ? fs::path(o.file)
                                         : fs::path(o.dir.empty() ? default_dir() : o.dir) / session_file_name(name);
            if (p.has_parent_path()) fs::create_directories(p.parent_path());
            sinks.push_back(std::make_shared<spdlog::sinks::basic_file_sink_mt>(p.string(), /*truncate=*/false));
            path = fs::absolute(p).string();
        } catch (const std::exception& e) {
            std::fprintf(stderr, "kigit: can't write a log file (%s); continuing without one\n", e.what());
        }
    }
    if (!sinks.empty()) sinks.back()->set_level(level_of(o.file_level));
    auto console = level_of(o.console_level);
    if (console != spdlog::level::off) {
        sinks.push_back(std::make_shared<spdlog::sinks::stderr_sink_mt>());
        sinks.back()->set_level(console);
    }
    if (sinks.empty()) sinks.push_back(std::make_shared<spdlog::sinks::null_sink_mt>());

    auto logger = std::make_shared<spdlog::logger>(name, sinks.begin(), sinks.end());
    logger->set_pattern(kPattern);
    logger->set_level(spdlog::level::debug); // each sink keeps its own level
    logger->flush_on(spdlog::level::debug);  // a crash shouldn't lose the log
    spdlog::set_default_logger(logger);
    return path;
}

void stop() {
    if (auto l = spdlog::default_logger()) l->flush();
    spdlog::shutdown();
}

} // namespace kigit::logging
