#include "parts/jlcparts.hpp"

#include "parts/store.hpp"
#include "utils/gzip.hpp"
#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>
#include <ctime>
#include <fstream>
#include <set>
#include <sstream>

namespace fs = std::filesystem;

namespace kigit::parts {

namespace {

constexpr const char* kIndex = "search-index.tsv.gz";
constexpr size_t kMaxHits = 60; // parts read in full for a word search

std::string read_file(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

void write_file(const fs::path& p, const std::string& data) {
    fs::create_directories(p.parent_path());
    fs::path tmp = p;
    tmp += ".tmp";
    {
        std::ofstream f(tmp, std::ios::binary);
        if (!(f << data)) throw std::runtime_error("cannot write " + tmp.string());
    }
    fs::rename(tmp, p);
}

long age_of(const fs::path& p) {
    std::error_code ec;
    if (!fs::exists(p, ec)) return -1;
    return static_cast<long>(std::time(nullptr) - platform::file_time(p));
}

std::string ago(long seconds) {
    long days = seconds / 86400, hours = seconds / 3600;
    if (days >= 1) return std::to_string(days) + (days == 1 ? " day" : " days") + " ago";
    if (hours >= 1) return std::to_string(hours) + (hours == 1 ? " hour" : " hours") + " ago";
    return "just now";
}

// "-55℃ 10kΩ 0603" -> the text matched against: Ω (any case) left out, so "10k" is a word.
std::string plain(std::string t) {
    for (const char* omega : {"\xCF\x89", "\xCE\xA9"})
        for (size_t at; (at = t.find(omega)) != std::string::npos;) t.erase(at, 2);
    return t;
}

std::string lower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// A word matches a piece of the text that is it, or starts with it and goes
// on with something that isn't a digit or a point: "10k" matches "10k" and
// "10k±1%", not "100k"; "resistor" matches "resistors".
bool has_word(const std::string& text, const std::string& w) {
    for (size_t at = text.find(w); at != std::string::npos; at = text.find(w, at + 1)) {
        bool starts = at == 0 || text[at - 1] == ' ' || text[at - 1] == '(' || text[at - 1] == ',';
        size_t end = at + w.size();
        bool ends = end >= text.size() || !(std::isdigit(static_cast<unsigned char>(text[end])) || text[end] == '.');
        if (starts && ends) return true;
    }
    return false;
}

std::string text_of(const nlohmann::json& v) { return v.is_string() ? v.get<std::string>() : ""; }

} // namespace

Jlcparts::Jlcparts(fs::path dir, net::Http http, long max_age) : Source(std::move(http), 0), dir_(std::move(dir)), max_age_(max_age) {}

fs::path Jlcparts::default_dir() { return app_dir() / "parts-lcsc"; }

bool Jlcparts::fetch(const std::string& name, const fs::path& to, std::string& error) {
    net::HttpRequest rq;
    rq.url = std::string(kBase) + name;
    rq.headers = {"User-Agent: kigit"};
    rq.timeout = 300;
    net::HttpResponse r = send(rq);
    if (r.status != 200) {
        error = !r.error.empty() ? r.error : "jlcparts answered " + std::to_string(r.status) + " for " + name;
        return false;
    }
    if (!gzip::gunzip(r.body)) { // check before keeping it
        error = name + " came back damaged";
        return false;
    }
    write_file(to, r.body);
    return true;
}

bool Jlcparts::refresh(std::string& error) {
    loaded_ = false;
    if (!fetch(kIndex, dir_ / kIndex, error)) return false;
    nlohmann::json meta = {{"downloaded", static_cast<long>(std::time(nullptr))}, {"source", std::string(kBase) + kIndex}};
    write_file(dir_ / "meta.json", meta.dump(1));
    spdlog::info("lcsc: downloaded jlcparts' index into {}", dir_.string());
    return true;
}

bool Jlcparts::load(std::string& error) {
    if (loaded_) {
        error = load_error_;
        return load_error_.empty();
    }
    loaded_ = true;
    fs::path index = dir_ / kIndex;
    long age = age_of(index);
    if (age < 0 || age > max_age_) {
        std::string why;
        if (!refresh(why)) {
            if (age < 0) { // nothing to fall back on
                load_error_ = "no LCSC parts data yet, and it couldn't be downloaded (" + why + "). Look up again when you're online";
                error = load_error_;
                return false;
            }
            notice_ = "LCSC data from " + ago(age) + " (couldn't refresh: " + why + ")";
            spdlog::warn("lcsc: {}", notice_);
        }
    }
    std::optional<std::string> text = gzip::gunzip(read_file(index));
    if (!text) {
        load_error_ = "the LCSC parts data in " + dir_.string() + " is damaged: delete the folder, then Look up again";
        error = load_error_;
        return false;
    }
    std::istringstream in(*text);
    for (std::string line; std::getline(in, line);) {
        size_t a = line.find('\t'), b = a == std::string::npos ? a : line.find('\t', a + 1);
        if (b == std::string::npos) continue;
        Entry e{line.substr(0, a), line.substr(a + 1, b - a - 1), plain(line.substr(b + 1))};
        size_t i = entries_.size();
        by_lcsc_[e.lcsc] = i;
        size_t s1 = e.text.find(' '), s2 = s1 == std::string::npos ? s1 : e.text.find(' ', s1 + 1);
        if (s1 != std::string::npos) by_mpn_[norm_pn(e.text.substr(s1 + 1, s2 == std::string::npos ? s2 : s2 - s1 - 1))].push_back(i);
        entries_.push_back(std::move(e));
    }
    spdlog::info("lcsc: {} parts in jlcparts' index", entries_.size());
    return true;
}

std::map<std::string, Offer> parse_jlcparts_shard(const std::string& jsonl) {
    std::map<std::string, Offer> out;
    std::istringstream in(jsonl);
    std::string line;
    if (!std::getline(in, line)) return out;
    nlohmann::json schema = nlohmann::json::parse(line, nullptr, false);
    if (!schema.is_object()) return out;
    auto at = [&](const nlohmann::json& row, const char* name) -> const nlohmann::json& {
        static const nlohmann::json none;
        auto k = schema.find(name);
        if (k == schema.end() || !k->is_number_integer()) return none;
        size_t i = k->get<size_t>();
        return i < row.size() ? row[i] : none;
    };
    while (std::getline(in, line)) {
        nlohmann::json row = nlohmann::json::parse(line, nullptr, false);
        if (!row.is_array()) continue;
        Offer o;
        o.site = "lcsc";
        o.sku = text_of(at(row, "lcsc"));
        if (o.sku.empty()) continue;
        o.mpn = text_of(at(row, "mfr"));
        o.description = text_of(at(row, "description"));
        o.datasheet = text_of(at(row, "datasheet"));
        o.url = "https://www.lcsc.com/product-detail/" + o.sku + ".html";
        o.currency = "USD";
        const auto& stock = at(row, "stock");
        o.stock = stock.is_number() ? stock.get<long>() : -1;
        for (const auto& b : at(row, "price"))
            if (b.is_object() && b.value("qFrom", 0) > 0 && b.contains("price") && b["price"].is_number())
                o.prices.push_back({b["qFrom"].get<int>(), b["price"].get<double>()});
        if (!o.prices.empty()) o.min_qty = o.prices.front().qty;
        out[o.sku] = std::move(o);
    }
    return out;
}

const std::map<std::string, Offer>* Jlcparts::shard(const std::string& name, std::string& error) {
    auto have = shards_.find(name);
    if (have != shards_.end()) return &have->second;
    if (name.find('/') != std::string::npos || name.find("..") != std::string::npos) return nullptr;
    fs::path file = dir_ / "shards" / name;
    long age = age_of(file);
    if ((age < 0 || age > max_age_) && !fetch(name, file, error) && age < 0) return nullptr; // offline: an old one will do
    std::optional<std::string> text = gzip::gunzip(read_file(file));
    if (!text) return nullptr;
    return &(shards_[name] = parse_jlcparts_shard(*text));
}

std::vector<Offer> Jlcparts::offers(const std::vector<size_t>& hits, std::string& error) {
    std::vector<Offer> out;
    for (size_t i : hits) {
        const Entry& e = entries_[i];
        std::string why;
        const auto* parts = shard(e.shard, why);
        if (parts)
            if (auto o = parts->find(e.lcsc); o != parts->end()) {
                out.push_back(o->second);
                continue;
            }
        // Not downloaded (offline): the part as the index has it, without price or stock.
        Offer bare;
        bare.site = "lcsc";
        bare.sku = e.lcsc;
        size_t s1 = e.text.find(' '), s2 = s1 == std::string::npos ? s1 : e.text.find(' ', s1 + 1);
        bare.mpn = s1 == std::string::npos ? "" : e.text.substr(s1 + 1, s2 == std::string::npos ? s2 : s2 - s1 - 1);
        bare.description = s2 == std::string::npos ? "" : e.text.substr(s2 + 1);
        bare.url = "https://www.lcsc.com/product-detail/" + e.lcsc + ".html";
        bare.note = "Price and stock not downloaded" + (why.empty() ? std::string() : " (" + why + ")");
        out.push_back(bare);
        if (error.empty()) error = why;
    }
    return out;
}

Search Jlcparts::part_number(const std::string& pn) {
    Search s;
    if (!load(s.error)) {
        s.fatal = true;
        return s;
    }
    std::vector<size_t> hits;
    std::string up = norm_pn(pn);
    bool lcsc = up.size() > 1 && up[0] == 'C' && std::all_of(up.begin() + 1, up.end(), [](char c) { return std::isdigit(static_cast<unsigned char>(c)); });
    if (lcsc) {
        if (auto it = by_lcsc_.find(up); it != by_lcsc_.end()) hits.push_back(it->second);
    } else if (auto it = by_mpn_.find(up); it != by_mpn_.end()) {
        hits = it->second;
    }
    std::string ignored;
    s.offers = offers(hits, ignored);
    return s;
}

Search Jlcparts::keyword(const std::string& words) {
    Search s;
    if (!load(s.error)) {
        s.fatal = true;
        return s;
    }
    std::vector<std::string> ws;
    std::istringstream in(lower(plain(words)));
    for (std::string w; in >> w;)
        if (w != "ohm" && w != "ohms") ws.push_back(w);
    if (ws.empty()) return s;
    // The longest word first: the fewest texts get past it.
    std::stable_sort(ws.begin(), ws.end(), [](const std::string& a, const std::string& b) { return a.size() > b.size(); });
    std::vector<size_t> hits;
    for (size_t i = 0; i < entries_.size() && hits.size() < kMaxHits; ++i) {
        const std::string& t = entries_[i].text;
        if (std::all_of(ws.begin(), ws.end(), [&](const std::string& w) { return has_word(t, w); })) hits.push_back(i);
    }
    std::string ignored;
    s.offers = offers(hits, ignored);
    return s;
}

nlohmann::json Jlcparts::info(const fs::path& dir) {
    nlohmann::json j = {{"dir", dir.string()}, {"source", "https://github.com/yaqwsx/jlcparts"}, {"have", false}};
    std::error_code ec;
    long age = age_of(dir / kIndex);
    if (age >= 0) {
        j["have"] = true;
        j["downloaded"] = static_cast<long>(std::time(nullptr)) - age;
        j["age"] = age;
        j["ago"] = ago(age);
    }
    uintmax_t bytes = 0;
    int shards = 0;
    for (const auto& e : fs::recursive_directory_iterator(dir, ec))
        if (e.is_regular_file(ec)) {
            bytes += e.file_size(ec);
            shards += e.path().parent_path().filename() == "shards";
        }
    j["bytes"] = bytes;
    j["shards"] = shards;
    return j;
}

} // namespace kigit::parts
