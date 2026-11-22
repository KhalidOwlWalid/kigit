#include "parts/store.hpp"

#include "parts/lookup.hpp"
#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <cctype>
#include <cstdlib>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace kigit::parts {

namespace {

nlohmann::json read_json(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return nlohmann::json::object();
    std::stringstream ss;
    ss << f.rdbuf();
    nlohmann::json j = nlohmann::json::parse(ss.str(), nullptr, false);
    if (!j.is_object()) {
        spdlog::warn("parts: ignoring {} (not a JSON object)", p.string());
        return nlohmann::json::object();
    }
    return j;
}

// Written whole to a temp file, then renamed over the old one.
void write_json(const fs::path& p, const nlohmann::json& j, bool private_file) {
    fs::create_directories(p.parent_path());
    fs::path tmp = p;
    tmp += ".tmp";
    {
        std::ofstream f(tmp, std::ios::binary);
        if (!(f << j.dump(1) << "\n")) throw std::runtime_error("cannot write " + tmp.string());
    }
    if (private_file) fs::permissions(tmp, fs::perms::owner_read | fs::perms::owner_write);
    fs::rename(tmp, p);
}

fs::path keys_file() { return app_dir() / "parts-keys.json"; }

} // namespace

fs::path app_dir() {
    // As the GUI does: with the logs moved, the rest goes in the folder above them.
    if (const char* e = std::getenv("KIGIT_LOG_DIR"); e && *e) return fs::absolute(fs::path(e)).parent_path();
    return platform::state_dir() / "kigit";
}

namespace {

std::string env(const char* name) {
    const char* e = std::getenv(name);
    return e ? e : "";
}

std::string label_of(const std::string& site) {
    return site == "digikey" ? "kigit: Digi-Key login (client ID and secret)" : "kigit: " + site_name(site) + " API key";
}

// The secret as it's kept in the file (the fallback): Mouser's key, or
// Digi-Key's {"client_id", "client_secret"} as JSON text; "" if none.
std::string file_secret(const nlohmann::json& keys, const std::string& site) {
    auto k = keys.find(site);
    if (k == keys.end()) return "";
    if (site != "digikey") return k->is_string() ? k->get<std::string>() : "";
    if (!k->is_object() || k->value("client_id", "").empty()) return "";
    return nlohmann::json{{"client_id", k->value("client_id", "")}, {"client_secret", k->value("client_secret", "")}}.dump();
}

void drop_file_secret(nlohmann::json& keys, const std::string& site) {
    if (site != "digikey") { keys.erase(site); return; }
    if (auto k = keys.find(site); k != keys.end() && k->is_object()) {
        k->erase("client_id");
        k->erase("client_secret");
    }
}

// A site's secret: from the keyring, else the file. One still in the file
// is moved into the keyring when there is one (checked, then taken out of
// the file).
std::string read_secret(const std::string& site) {
    nlohmann::json keys = read_json(keys_file());
    std::string in_file = file_secret(keys, site);
    if (!platform::keyring().available) return in_file;
    if (auto v = platform::secret_get(site); v && !v->empty()) {
        if (!in_file.empty()) { // an old copy: the keyring's is the one
            drop_file_secret(keys, site);
            write_json(keys_file(), keys, true);
        }
        return *v;
    }
    if (in_file.empty()) return "";
    if (platform::secret_set(site, label_of(site), in_file) && platform::secret_get(site) == in_file) {
        drop_file_secret(keys, site);
        write_json(keys_file(), keys, true);
        spdlog::info("parts: moved the {} key from {} into {}", site, keys_file().filename().string(),
                     platform::keyring().name);
    } else {
        spdlog::warn("parts: couldn't move the {} key into {}; it stays in {}", site, platform::keyring().name,
                     keys_file().string());
    }
    return in_file;
}

// Saves (or with "" removes) a site's secret: in the keyring when there is
// one, else in the file (owner only). Returns where it went.
std::string write_secret(const std::string& site, const std::string& value) {
    nlohmann::json keys = read_json(keys_file());
    drop_file_secret(keys, site);
    bool ring = platform::keyring().available;
    if (value.empty()) {
        if (ring) platform::secret_delete(site);
        write_json(keys_file(), keys, true);
        return "";
    }
    if (ring && platform::secret_set(site, label_of(site), value) && platform::secret_get(site) == value) {
        write_json(keys_file(), keys, true);
        return "keyring";
    }
    if (ring) spdlog::warn("parts: couldn't save the {} key in {}; it's in {} instead", site, platform::keyring().name,
                           keys_file().string());
    if (site == "digikey") {
        nlohmann::json d = nlohmann::json::parse(value);
        if (!keys["digikey"].is_object()) keys["digikey"] = nlohmann::json::object();
        keys["digikey"]["client_id"] = d.value("client_id", "");
        keys["digikey"]["client_secret"] = d.value("client_secret", "");
    } else {
        keys[site] = value;
    }
    write_json(keys_file(), keys, true);
    return "file";
}

} // namespace

std::string api_key(const std::string& site) {
    std::string var = "KIGIT_";
    for (char c : site) var += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    var += "_API_KEY";
    if (const char* e = std::getenv(var.c_str()); e && *e) return e;
    return read_secret(site);
}

std::string set_api_key(const std::string& site, const std::string& key) { return write_secret(site, key); }

DigiKeyLogin digikey_login() {
    DigiKeyLogin l;
    if (!env("KIGIT_DIGIKEY_CLIENT_ID").empty()) {
        l.client_id = env("KIGIT_DIGIKEY_CLIENT_ID");
        l.client_secret = env("KIGIT_DIGIKEY_CLIENT_SECRET");
    } else if (std::string secret = read_secret("digikey"); !secret.empty()) {
        nlohmann::json j = nlohmann::json::parse(secret, nullptr, false);
        if (j.is_object()) {
            l.client_id = j.value("client_id", "");
            l.client_secret = j.value("client_secret", "");
        }
    }
    nlohmann::json keys = read_json(keys_file());
    if (auto d = keys.find("digikey"); d != keys.end() && d->is_object()) {
        l.site = d->value("site", l.site);
        l.currency = d->value("currency", l.currency);
    }
    if (!env("KIGIT_DIGIKEY_SITE").empty()) l.site = env("KIGIT_DIGIKEY_SITE");
    if (!env("KIGIT_DIGIKEY_CURRENCY").empty()) l.currency = env("KIGIT_DIGIKEY_CURRENCY");
    return l;
}

std::string set_digikey_login(const DigiKeyLogin& l) {
    std::string where = write_secret("digikey", l.client_id.empty() ? "" : nlohmann::json{
        {"client_id", l.client_id}, {"client_secret", l.client_secret}}.dump());
    // Which Digi-Key site and currency aren't secret: the file.
    nlohmann::json keys = read_json(keys_file());
    if (l.client_id.empty()) {
        keys.erase("digikey");
    } else {
        if (!keys["digikey"].is_object()) keys["digikey"] = nlohmann::json::object();
        keys["digikey"]["site"] = l.site;
        keys["digikey"]["currency"] = l.currency;
    }
    write_json(keys_file(), keys, true);
    return where;
}

std::string key_place(const std::string& site) {
    if (site == "lcsc") return has_key(site) ? "none needed" : "";
    if (key_from_env(site)) return "env";
    if (!has_key(site)) return "";
    return platform::keyring().available && platform::secret_get(site) ? "keyring" : "file";
}

fs::path keys_path() { return keys_file(); }

bool has_key(const std::string& site) {
    if (site == "lcsc") return env("KIGIT_LCSC") != "off"; // no key: jlcparts' data
    if (site == "digikey") {
        DigiKeyLogin l = digikey_login();
        return !l.client_id.empty() && !l.client_secret.empty();
    }
    return !api_key(site).empty();
}

bool key_from_env(const std::string& site) {
    if (site == "digikey") return !env("KIGIT_DIGIKEY_CLIENT_ID").empty();
    std::string var = "KIGIT_";
    for (char c : site) var += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return !env((var + "_API_KEY").c_str()).empty();
}

Cache::Cache(fs::path file) : file_(std::move(file)) {
    data_ = read_json(file_);
}

fs::path Cache::default_file() { return app_dir() / "parts-cache.json"; }

std::optional<nlohmann::json> Cache::get(const std::string& key, long max_age) const {
    auto e = data_.find(key);
    if (e == data_.end() || !e->is_object()) return std::nullopt;
    long age = static_cast<long>(std::time(nullptr)) - e->value("time", 0L);
    if (age < 0 || age > max_age || !e->contains("value")) return std::nullopt;
    return (*e)["value"];
}

void Cache::put(const std::string& key, const nlohmann::json& value) {
    data_[key] = {{"time", static_cast<long>(std::time(nullptr))}, {"value", value}};
    dirty_ = true;
}

void Cache::save() const {
    if (!dirty_) return;
    // Old answers are dropped (older than a week).
    nlohmann::json keep = nlohmann::json::object();
    long now = static_cast<long>(std::time(nullptr));
    for (const auto& [k, v] : data_.items())
        if (v.is_object() && now - v.value("time", 0L) < 7 * 24 * 3600) keep[k] = v;
    write_json(file_, keep, false);
}

} // namespace kigit::parts
