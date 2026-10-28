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

} // namespace

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
    if (o.console) sinks.push_back(std::make_shared<spdlog::sinks::stderr_sink_mt>());
    if (sinks.empty()) sinks.push_back(std::make_shared<spdlog::sinks::null_sink_mt>());

    auto logger = std::make_shared<spdlog::logger>(name, sinks.begin(), sinks.end());
    logger->set_pattern(kPattern);
    logger->set_level(o.debug ? spdlog::level::debug : spdlog::level::info);
    logger->flush_on(spdlog::level::info); // a crash shouldn't lose the log
    spdlog::set_default_logger(logger);
    return path;
}

void stop() {
    if (auto l = spdlog::default_logger()) l->flush();
    spdlog::shutdown();
}

} // namespace kigit::logging
