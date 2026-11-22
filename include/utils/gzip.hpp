#pragma once
// Reading .gz files (one gzip member), with miniz.
#include <optional>
#include <string>

namespace kigit::gzip {

// What a .gz file holds; nullopt if it isn't gzip, or is damaged or cut short.
std::optional<std::string> gunzip(const std::string& gz);

} // namespace kigit::gzip
