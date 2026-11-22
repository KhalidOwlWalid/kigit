// End-to-end tests: the real kigit binary on the fixture repo.
#include "helpers.hpp"
#include "utils/platform.hpp"

#include <doctest/doctest.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <fstream>
#include <set>

using namespace kigit::test;
using nlohmann::json;

namespace {

json parse(const RunResult& r) {
    INFO("stderr: " << r.err);
    REQUIRE(r.code == 0);
    return json::parse(r.out);
}

} // namespace

TEST_SUITE("cli") {

TEST_CASE("--version and --help") {
    CHECK(run_kigit("--version").out.rfind("kigit ", 0) == 0);
    RunResult help = run_kigit("--help");
    CHECK(help.code == 0);
    CHECK(help.out.find("--kicad-only") != std::string::npos);
}

TEST_CASE("--projects finds the project up to --depth levels down") {
    TempDir tmp;
    make_fixture_repo(tmp / "repo");
    json found = parse(run_kigit("--projects -C " + quote(tmp.path().string())));
    REQUIRE(found["projects"].size() == 1);
    const json& p = found["projects"][0];
    CHECK(p["name"] == "demo");
    CHECK(p["level"] == 2);
    CHECK(p["pcb"] == true);
    CHECK(p["git"] == true);
    CHECK(parse(run_kigit("--projects --depth 1 -C " + quote(tmp.path().string())))["projects"].empty());

    // Not in git: found, but flagged.
    write_text(tmp / "loose/x.kicad_pro", "{}");
    write_text(tmp / "loose/x.kicad_pcb", "(kicad_pcb)");
    json loose = parse(run_kigit("--projects -C " + quote((tmp / "loose").string())));
    REQUIRE(loose["projects"].size() == 1);
    CHECK(loose["projects"][0]["git"] == false);
}

TEST_CASE("--log: all commits, tags, filters and the renamed folder") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());

    json log = parse(run_kigit("--log -C " + board));
    REQUIRE(log["commits"].size() == 4);
    CHECK(log["total"] == 4);
    CHECK(log["local"]["dirty"] == false);
    auto folders = log["folders"].get<std::vector<std::string>>();
    CHECK(std::find(folders.begin(), folders.end(), "hw") != folders.end()); // followed the rename
    // Newest first: move, v2, docs, v1. Only "docs only" didn't touch the board.
    CHECK(log["commits"][2]["subject"] == "docs only");
    CHECK(log["commits"][2]["pcb"] == false);
    CHECK(log["commits"][3]["pcb"] == true); // v1, in the old hw/ folder
    CHECK(log["commits"][3]["sch"] == true);
    CHECK(log["commits"][0]["parent"] == log["commits"][1]["hash"]);
    CHECK(log["commits"][3]["parent"] == "");
    CHECK(log["user"]["name"] == "kigit tests"); // from the repo's git config
    CHECK(log["head"] == log["commits"][0]["hash"]);

    json kicad = parse(run_kigit("--log --kicad-only --max 0 -C " + board));
    CHECK(kicad["commits"].size() == 3);

    json limited = parse(run_kigit("--log --max 2 -C " + board));
    CHECK(limited["commits"].size() == 2);
    CHECK(limited["total"] == 4);

    // A bare date is the whole day (the v2 commit is at 12:00 that day).
    json day = parse(run_kigit("--log --since 2025-03-01 --until 2025-03-01 -C " + board));
    REQUIRE(day["commits"].size() == 1);
    CHECK(day["commits"][0]["subject"] == "v2: add C1, move R2, widen a track");

    write_text(tmp / "board/demo.kicad_pcb", read_text(tmp / "board/demo.kicad_pcb") + "\n");
    json dirty = parse(run_kigit("--log -C " + board));
    CHECK(dirty["local"]["dirty"] == true);
    CHECK(dirty["local"]["pcb"] == true);
}

TEST_CASE("kigit bom: the working tree, a commit, CSV and JSON") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());

    RunResult table = run_kigit("bom --no-log -C " + board);
    REQUIRE(table.code == 0);
    CHECK(table.out.find("R1 R3 R5") != std::string::npos);
    CHECK(table.out.find("4 lines, 6 parts") != std::string::npos);

    json j = parse(run_kigit("bom --no-log --json HEAD -C " + board));
    CHECK(j["meta"]["rev"]["local"] == false);
    CHECK(j["summary"]["parts"] == 6);
    CHECK(j["lines"][0]["links"]["digikey"].get<std::string>().starts_with("https://www.digikey.com/"));

    RunResult csv = run_kigit("bom --no-log --csv -C " + board);
    CHECK(csv.out.starts_with("Qty,References,Value,"));
    CHECK(csv.err.empty()); // stdout has the data, nothing else goes there

    // Outside git: the files on disk, but no revisions.
    TempDir elsewhere; // not inside the fixture repo
    fs::path loose = elsewhere / "loose";
    fs::create_directories(loose);
    fs::copy_file(fixture("v1/demo.kicad_sch"), loose / "demo.kicad_sch");
    CHECK(run_kigit("bom --no-log " + quote((loose / "demo.kicad_sch").string())).code == 0);
    RunResult no_git = run_kigit("bom --no-log HEAD " + quote((loose / "demo.kicad_sch").string()));
    CHECK(no_git.code == 1);
    CHECK(no_git.err.find("not in a git repository") != std::string::npos);
    CHECK(run_kigit("bom --nope").code == 2);
}

#ifndef _WIN32
TEST_CASE("kigit bom --lookup: Mouser through curl, the key on stdin only, answers kept") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());
    fs::path bin = tmp / "bin";
    fs::create_directories(bin);
    // A stand-in curl: notes its arguments and the config it was given, and
    // answers with a recorded Mouser reply.
    json part = {{"MouserPartNumber", "603-RC0603FR-071KL"}, {"ManufacturerPartNumber", "RC0603FR-071KL"},
                 {"Manufacturer", "YAGEO"}, {"Description", "Thick Film Resistors - SMD 1K OHM 1% 0603"},
                 {"AvailabilityInStock", "5000"}, {"Min", "1"}, {"Mult", "1"},
                 {"PriceBreaks", {{{"Quantity", 1}, {"Price", "$0.10"}, {"Currency", "USD"}}}}};
    write_text(bin / "reply.json", json{{"Errors", json::array()}, {"SearchResults", {{"Parts", {part}}}}}.dump());
    fs::path curl = bin / "curl";
    std::ofstream(curl) << "#!/bin/sh\n"
                           "echo \"$*\" >> \"" << (bin / "args.log").string() << "\"\n"
                           "cat >> \"" << (bin / "config.txt").string() << "\"\n"
                           "cat \"" << (bin / "reply.json").string() << "\"\n"
                           "printf '\\n200'\n";
    fs::permissions(curl, fs::perms::owner_all);
    kigit::platform::set_env("KIGIT_CURL", curl.string());
    kigit::platform::set_env("XDG_STATE_HOME", (tmp / "state").string());
    kigit::platform::set_env("KIGIT_LOOKUP_PACE_MS", "0");
    kigit::platform::set_env("KIGIT_MOUSER_API_KEY", "");
    kigit::platform::set_env("KIGIT_LOG_DIR", ""); // else the keys go in the folder above it
    kigit::platform::set_env("KIGIT_KEYRING", "off");  // the file (the keyring's test is below)
    kigit::platform::set_env("KIGIT_LCSC", "off");     // no downloads from jlcparts in tests

    // No key yet: every line skipped, and why.
    RunResult none = run_kigit("bom --no-log --lookup --json -C " + board);
    json j = parse(none);
    CHECK(j["lines"][0]["sites"]["mouser"]["status"] == "skipped");
    CHECK(none.err.find("--set-key mouser") != std::string::npos);

    CHECK(parse(run_kigit("bom --no-log --keys"))["mouser"]["set"] == false);
    RunResult set = run("printf 'MY-KEY\\n' | " + quote(KIGIT_BIN) + " bom --no-log --set-key mouser");
    REQUIRE(set.code == 0);
    fs::path keys = tmp / "state/kigit/parts-keys.json";
    CHECK(json::parse(read_text(keys))["mouser"] == "MY-KEY");
    json status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["mouser"]["set"] == true);
    CHECK(status.dump().find("MY-KEY") == std::string::npos);
    CHECK((fs::status(keys).permissions() & (fs::perms::group_all | fs::perms::others_all)) == fs::perms::none);

    RunResult looked = run_kigit("bom --no-log --lookup --json --boards 10 -C " + board);
    j = parse(looked);
    CHECK(j["summary"]["boards"] == 10);
    CHECK(j["lines"][1]["need"] == 30); // R1 R3 R5 for 10 boards
    CHECK(j["lines"][0]["sites"]["mouser"]["status"] == "choose");
    CHECK(j["lines"][0]["sites"]["mouser"]["candidates"][0]["sku"] == "603-RC0603FR-071KL");
    CHECK(read_text(bin / "config.txt").find("apiKey=MY-KEY") != std::string::npos);
    std::string args = read_text(bin / "args.log");
    CHECK(args.find("MY-KEY") == std::string::npos); // never on a command line
    CHECK(args.find("-K -") != std::string::npos);
    size_t calls = std::count(args.begin(), args.end(), '\n');
    CHECK(calls == 4); // one per line

    // Again: from the cache. --refresh asks again.
    run_kigit("bom --no-log --lookup -C " + board);
    args = read_text(bin / "args.log");
    CHECK(static_cast<size_t>(std::count(args.begin(), args.end(), '\n')) == calls);
    RunResult table = run_kigit("bom --no-log --lookup --refresh -C " + board);
    CHECK(table.code == 0);
    CHECK(table.out.find("choose (1 options)") != std::string::npos);
    args = read_text(bin / "args.log");
    CHECK(static_cast<size_t>(std::count(args.begin(), args.end(), '\n')) == 2 * calls);

    CHECK(run_kigit("bom --no-log --lookup --boards 0 -C " + board).code == 2);

    // Digi-Key: client ID, secret and locale, one per line on stdin.
    std::string set_dk = "printf 'DK-ID\\nDK-SECRET\\nUK GBP\\n' | " + quote(KIGIT_BIN) + " bom --no-log --set-key digikey";
    REQUIRE(run(set_dk).code == 0);
    json dk = json::parse(read_text(keys))["digikey"];
    CHECK(dk["client_id"] == "DK-ID");
    CHECK(dk["client_secret"] == "DK-SECRET");
    CHECK(dk["currency"] == "GBP");
    status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["digikey"]["set"] == true);
    CHECK(status["digikey"]["site"] == "UK");
    CHECK(status.dump().find("DK-SECRET") == std::string::npos);
    CHECK(run("printf 'DK-ID\\n' | " + quote(KIGIT_BIN) + " bom --no-log --set-key digikey").code == 1); // no secret
    REQUIRE(run("printf '\\n' | " + quote(KIGIT_BIN) + " bom --no-log --set-key digikey").code == 0);    // removed
    CHECK(parse(run_kigit("bom --no-log --keys"))["digikey"]["set"] == false);
    CHECK(json::parse(read_text(keys))["mouser"] == "MY-KEY"); // the other key stays
    for (const char* v : {"KIGIT_CURL", "XDG_STATE_HOME", "KIGIT_LOOKUP_PACE_MS", "KIGIT_KEYRING", "KIGIT_LCSC"}) kigit::platform::set_env(v, "");
}

TEST_CASE("kigit bom --set-key: keys go into the keyring (secret on stdin), and move there from the file") {
    TempDir tmp;
    fs::path ring = tmp / "ring", state = tmp / "state";
    fs::create_directories(ring);
    // A stand-in secret-tool: keeps each secret as a file named by its name
    // attribute, and notes its arguments.
    fs::path tool = tmp / "secret-tool";
    std::ofstream(tool) << "#!/bin/sh\n"
                           "D=\"" << ring.string() << "\"\n"
                           "echo \"$*\" >> \"$D/args.log\"\n"
                           "cmd=$1; shift; name=; prev=\n"
                           "for a in \"$@\"; do [ \"$prev\" = name ] && name=$a; prev=$a; done\n"
                           "case $cmd in\n"
                           "  store) cat > \"$D/s_$name\" ;;\n"
                           "  lookup) [ -f \"$D/s_$name\" ] && cat \"$D/s_$name\" || exit 1 ;;\n"
                           "  clear) rm -f \"$D/s_$name\" ;;\n"
                           "esac\n";
    fs::permissions(tool, fs::perms::owner_all);
    kigit::platform::set_env("KIGIT_SECRET_TOOL", tool.string());
    kigit::platform::set_env("XDG_STATE_HOME", state.string());
    kigit::platform::set_env("KIGIT_LOG_DIR", "");
    kigit::platform::set_env("KIGIT_MOUSER_API_KEY", "");
    kigit::platform::set_env("KIGIT_KEYRING", "");
    fs::path keys = state / "kigit/parts-keys.json";
    std::string bin = quote(KIGIT_BIN);

    // Saved: into the keyring, through stdin; the file has none of it.
    RunResult set = run("printf 'RING-KEY\\n' | " + bin + " bom --no-log --set-key mouser");
    REQUIRE(set.code == 0);
    CHECK(set.err.find("keyring") != std::string::npos);
    CHECK(read_text(ring / "s_mouser") == "RING-KEY");
    CHECK(read_text(ring / "args.log").find("RING-KEY") == std::string::npos); // never an argument
    CHECK((!fs::exists(keys) || read_text(keys).find("RING-KEY") == std::string::npos));
    json status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["mouser"]["set"] == true);
    CHECK(status["mouser"]["where"] == "keyring");
    CHECK(status["store"]["keyring"] == true);
    CHECK(status.dump().find("RING-KEY") == std::string::npos);

    // Digi-Key: the ID and secret in the keyring, the site and currency in the file.
    REQUIRE(run("printf 'DK-ID\\nDK-SECRET\\nUK GBP\\n' | " + bin + " bom --no-log --set-key digikey").code == 0);
    CHECK(read_text(ring / "s_digikey").find("DK-SECRET") != std::string::npos);
    json file = json::parse(read_text(keys));
    CHECK(file["digikey"]["currency"] == "GBP");
    CHECK(!file["digikey"].contains("client_secret"));
    status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["digikey"]["where"] == "keyring");
    CHECK(status["digikey"]["site"] == "UK");

    // Removed: from the keyring too.
    REQUIRE(run("printf '\\n' | " + bin + " bom --no-log --set-key mouser").code == 0);
    CHECK(!fs::exists(ring / "s_mouser"));

    // A key left in the file (from an older kigit) moves into the keyring when it's next read.
    file = json::parse(read_text(keys));
    file["mouser"] = "OLD-FILE-KEY";
    write_text(keys, file.dump());
    status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["mouser"]["where"] == "keyring");
    CHECK(read_text(ring / "s_mouser") == "OLD-FILE-KEY");
    CHECK(read_text(keys).find("OLD-FILE-KEY") == std::string::npos);

    // No keyring answering: the file, and said so.
    fs::path broken = tmp / "broken-tool";
    std::ofstream(broken) << "#!/bin/sh\necho 'Cannot autolaunch D-Bus without X11 $DISPLAY' >&2\nexit 1\n";
    fs::permissions(broken, fs::perms::owner_all);
    kigit::platform::set_env("KIGIT_SECRET_TOOL", broken.string());
    RunResult fallback = run("printf 'FILE-KEY\\n' | " + bin + " bom --no-log --set-key mouser");
    REQUIRE(fallback.code == 0);
    CHECK(fallback.err.find("not encrypted") != std::string::npos);
    CHECK(fallback.err.find("D-Bus") != std::string::npos);
    CHECK(json::parse(read_text(keys))["mouser"] == "FILE-KEY");
    status = parse(run_kigit("bom --no-log --keys"));
    CHECK(status["mouser"]["where"] == "file");
    CHECK(status["store"]["keyring"] == false);
    for (const char* v : {"KIGIT_SECRET_TOOL", "XDG_STATE_HOME"}) kigit::platform::set_env(v, "");
}
#endif

TEST_CASE("kigit bom --write: part information only, checked, with a backup to restore") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    fs::path sch = tmp / "board/demo.kicad_sch";
    const std::string before = read_text(sch);
    auto write = [&](const std::string& edits, const std::string& extra = "") {
        write_text(tmp / "edits.json", edits);
        return run_kigit("bom --no-log --write " + quote((tmp / "edits.json").string()) + " " + extra + " " +
                         quote(sch.string()));
    };

    // Refused, and nothing written: KiCad's own fields, unknown parts, a commit.
    RunResult r = write(R"([{"refs": ["R1"], "field": "Value", "value": "2k"}])");
    CHECK(r.code == 1);
    CHECK(r.err.find("KiCad's own fields") != std::string::npos);
    CHECK(write(R"([{"refs": ["R99"], "field": "MPN", "value": "x"}])").code == 1);
    CHECK(write(R"([{"refs": ["R1"], "field": "MPN", "value": "x"}])", "HEAD").code == 1);
    CHECK(read_text(sch) == before);

    // KiCad has it open: refused unless --force.
    write_text(tmp / "board/~demo.kicad_sch.lck", "");
    r = write(R"([{"refs": ["R1", "R3"], "field": "MPN", "value": "RC0603FR-071KL"}])");
    CHECK(r.code == 1);
    CHECK(r.err.find("KiCad has demo.kicad_sch open") != std::string::npos);
    CHECK(read_text(sch) == before);
    r = write(R"([{"refs": ["R1", "R3"], "field": "MPN", "value": "RC0603FR-071KL"}])", "--force");
    REQUIRE(r.code == 0);
    fs::remove(tmp / "board/~demo.kicad_sch.lck");
    json out = json::parse(r.out);
    CHECK(out["fields"] == 2);
    CHECK(out["written"] == json::array({"demo.kicad_sch"}));

    // The BOM sees it; the backup puts the file back as it was.
    json bom = parse(run_kigit("bom --no-log --json " + quote(sch.string())));
    bool found = false;
    for (const auto& l : bom["lines"])
        if (l["mpn"] == "RC0603FR-071KL") found = l["refs"] == json::array({"R1", "R3"});
    CHECK(found);
    CHECK(fs::exists(tmp / "board/.kigit/.gitignore"));
    RunResult back = run_kigit("bom --no-log --restore " + quote(out["backup"].get<std::string>()));
    CHECK(back.code == 0);
    CHECK(read_text(sch) == before);
    CHECK(run_kigit("bom --no-log --restore " + quote(tmp.path().string())).code == 1); // not a backup folder

    // Renaming a field (a column's title): the values move to the new name.
    REQUIRE(write(R"([{"refs": ["R1", "R3"], "field": "Voltage", "value": "50V"}])").code == 0);
    r = write(R"([{"refs": ["R1", "R2", "R3"], "field": "Voltage", "rename": "Voltage rating"}])");
    REQUIRE(r.code == 0);
    CHECK(json::parse(r.out)["fields"] == 2); // R2 has no Voltage field: left alone
    std::string after = read_text(sch);
    auto count = [&](const std::string& what) {
        int n = 0;
        for (size_t at = after.find(what); at != std::string::npos; at = after.find(what, at + 1)) ++n;
        return n;
    };
    CHECK(count("(property \"Voltage rating\" \"50V\"") == 2);
    CHECK(count("(property \"Voltage\"") == 0);
    CHECK(write(R"([{"refs": ["R1"], "field": "Voltage rating", "rename": "Footprint"}])").code == 1); // KiCad's own
}

TEST_CASE("--rewritten: where an amended commit went") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string dir = quote(tmp.path().string());
    std::string before = run("git -C " + dir + " rev-parse HEAD").out.substr(0, 40);
    REQUIRE(run("git -C " + dir + " commit -q --amend -m reworded").code == 0);
    std::string after = run("git -C " + dir + " rev-parse HEAD").out.substr(0, 40);

    json r = parse(run_kigit("--rewritten " + before + " " + after + " -C " + dir));
    REQUIRE(r["commits"].size() == 2);
    CHECK(r["commits"][0]["live"] == false);
    REQUIRE(r["commits"][0]["matches"].size() == 1);
    CHECK(r["commits"][0]["matches"][0]["hash"] == after);
    CHECK(r["commits"][0]["matches"][0]["subject"] == "reworded");
    CHECK(r["commits"][1]["live"] == true);
    CHECK(run_kigit("--rewritten HEAD -C " + dir).code == 2); // hashes only
}

#ifndef _WIN32
// A stand-in kicad-cli: says `version` (or fails it, for "unknown"), turns
// down what KiCad 8 doesn't have (as KiCad does: "Unknown argument"), and
// writes a placeholder where a real one would write its output. Every call
// is logged, so the test can see what kigit asked for.
static fs::path fake_kicad_cli(const fs::path& dir, const std::string& version) {
    fs::path cli = dir / "kicad-cli";
    std::ofstream(cli) << "#!/bin/sh\n"
                          "echo \"$*\" >> \"" << (dir / "calls.log").string() << "\"\n"
                          "if [ \"$1\" = version ]; then " << (version.empty() ? "exit 1" : "echo " + version) << "; exit 0; fi\n"
                          "if [ \"$1 $2\" = \"pcb render\" ]; then echo 'Unknown argument: render' >&2; exit 1; fi\n"
                          "out=''; prev=''\n"
                          "for a in \"$@\"; do\n"
                          "  case \"$a\" in --include-pads|--include-silkscreen|--include-soldermask) "
                          "echo \"Unknown argument: $a\" >&2; exit 1;; esac\n"
                          "  [ \"$prev\" = --output ] && out=\"$a\"; prev=\"$a\"\n"
                          "done\n"
                          "echo placeholder > \"$out\"\n";
    fs::permissions(cli, fs::perms::owner_all);
    return cli;
}

TEST_CASE("--3d and --render with KiCad 8 (or an older kicad-cli)") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string dir = quote((tmp / "board").string());
    // The fixture board is in KiCad 10's format, which KiCad 8 can't read: the
    // working tree's copy (what --3d and --render use by default) as KiCad 8's.
    fs::path pcb = tmp / "board" / "demo.kicad_pcb";
    std::string text = read_text(pcb);
    size_t at = text.find("(version ");
    REQUIRE(at != std::string::npos);
    text.replace(at, text.find(')', at) - at + 1, "(version 20240108)");
    std::ofstream(pcb, std::ios::binary) << text;
    for (const std::string version : {"8.0.5", ""}) {  // KiCad 8, and one whose version is unknown
        CAPTURE(version);
        fs::path bin = tmp / ("cli" + version);
        fs::create_directories(bin);
        kigit::platform::set_env("KIGIT_KICAD_CLI", fake_kicad_cli(bin, version).string());
        RunResult made = run_kigit("--3d -o " + quote((tmp / "b.glb").string()) + " -C " + dir);
        INFO("stderr: " << made.err);
        CHECK(made.code == 0);
        CHECK(made.err.find("without pads, silkscreen or solder mask") != std::string::npos);  // said
        std::string calls = read_text(bin / "calls.log");
        CHECK(calls.find("pcb export glb --include-tracks --include-zones --force --output") != std::string::npos);

        RunResult pic = run_kigit("--render -o " + quote((tmp / "pic.png").string()) + " -C " + dir);
        INFO("stderr: " << pic.err);
        CHECK(pic.code == 0);
        CHECK(pic.out.find("pic.svg") != std::string::npos);  // no 3D render: a 2D picture, as .svg
        CHECK(fs::exists(tmp / "pic.svg"));
        CHECK(read_text(bin / "calls.log").find("pcb export svg --layers") != std::string::npos);
        fs::remove(tmp / "pic.svg");
    }
    // A board saved by a newer KiCad than KiCad 8 can read: said in words.
    fs::path bin = tmp / "cli8.0.5";  // the KiCad 8 one from above
    kigit::platform::set_env("KIGIT_KICAD_CLI", (bin / "kicad-cli").string());
    fs::path newer = tmp / "newer" / "x.kicad_pcb";
    fs::create_directories(newer.parent_path());
    std::ofstream(newer) << "(kicad_pcb\n\t(version 20241229)\n\t(generator \"pcbnew\")\n)\n";
    RunResult old = run_kigit("--render -o " + quote((tmp / "n.png").string()) + " -C " + quote(newer.string()));
    CHECK(old.code == 1);
    CHECK(old.err.find("saved by a newer KiCad (file version 20241229)") != std::string::npos);
    kigit::platform::set_env("KIGIT_KICAD_CLI", "");
}
#endif

#ifndef _WIN32
TEST_CASE("--3d --disk: a board file on disk, no git") {
    TempDir tmp;
    fs::path folder = tmp / "copy";  // not a git repository
    fs::create_directories(folder / "3d");
    fs::copy_file(fixture("v2/demo.kicad_pcb"), folder / "demo.kicad_pcb");
    fs::copy_file(fixture("demo.kicad_pro"), folder / "demo.kicad_pro");
    std::ofstream(folder / "3d" / "part.step") << "ISO-10303-21;";
    fs::path bin = tmp / "cli";
    fs::create_directories(bin);
    // A stand-in kicad-cli that also notes which files it was given next to the board.
    fs::path cli = bin / "kicad-cli";
    std::ofstream(cli) << "#!/bin/sh\n"
                          "if [ \"$1\" = version ]; then echo 10.0.0; exit 0; fi\n"
                          "out=''; prev=''; last=''\n"
                          "for a in \"$@\"; do [ \"$prev\" = --output ] && out=\"$a\"; prev=\"$a\"; last=\"$a\"; done\n"
                          "ls -R \"$(dirname \"$last\")\" > \"" << (bin / "seen.txt").string() << "\"\n"
                          "echo placeholder > \"$out\"\n";
    fs::permissions(cli, fs::perms::owner_all);
    kigit::platform::set_env("KIGIT_KICAD_CLI", cli.string());
    std::string glb = (tmp / "b.glb").string();
    RunResult made = run_kigit("--3d --disk " + quote((folder / "demo.kicad_pcb").string()) + " -o " + quote(glb));
    INFO("stderr: " << made.err);
    CHECK(made.code == 0);
    CHECK(fs::exists(glb));
    std::string seen = read_text(bin / "seen.txt");
    CHECK(seen.find("demo.kicad_pro") != std::string::npos);  // its project file came along
    CHECK(seen.find("part.step") != std::string::npos);       // and its folder's 3D models
    CHECK(run_kigit("--3d --disk " + quote((tmp / "nope.kicad_pcb").string())).code == 1);
    kigit::platform::set_env("KIGIT_KICAD_CLI", "");
    CHECK(run_kigit("--disk " + quote((folder / "demo.kicad_pcb").string())).code == 2);  // only with --3d
    CHECK(run_kigit("--3d --disk HEAD " + quote((folder / "demo.kicad_pcb").string())).code == 2);  // no revisions
}
#endif

TEST_CASE("--3d: one revision, made by kicad-cli") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string dir = quote((tmp / "board").string());
    CHECK(run_kigit("--3d HEAD~1 HEAD -C " + dir).code == 2); // one revision only

    // Without kicad-cli: a clear message.
    kigit::platform::set_env("KIGIT_KICAD_CLI", (tmp / "no-kicad-cli").string());
    RunResult missing = run_kigit("--3d -C " + dir);
    CHECK(missing.code == 1);
    CHECK(missing.err.find("kicad-cli") != std::string::npos);
    kigit::platform::set_env("KIGIT_KICAD_CLI", "");

    // With KiCad installed: a real .glb (binary glTF) of an older commit,
    // whose board was in another folder then.
    if (!kigit::platform::find_kicad_cli()) return;
    std::string glb = (tmp / "out.glb").string();
    RunResult made = run_kigit("--3d HEAD~1 -o " + quote(glb) + " -C " + dir);
    INFO("stderr: " << made.err);
    REQUIRE(made.code == 0);
    CHECK(made.out.find("out.glb") != std::string::npos);
    CHECK(read_text(glb).substr(0, 4) == "glTF");

    // A part whose model file doesn't exist: listed on stderr for the GUI.
    std::string pcb = read_text(tmp / "board/demo.kicad_pcb");
    size_t fp = pcb.find("(footprint \"Demo:R\"");
    REQUIRE(fp != std::string::npos);
    pcb.insert(pcb.find('\n', fp) + 1, "\t\t(model \"${KIPRJMOD}/no-such-model.step\")\n");
    write_text(tmp / "board/demo.kicad_pcb", pcb);
    RunResult lacking = run_kigit("--3d -o " + quote((tmp / "local.glb").string()) + " -C " + dir);
    INFO("stderr: " << lacking.err);
    CHECK(lacking.code == 0);
    CHECK(lacking.err.find("1 part has no 3D model") != std::string::npos);
    CHECK(lacking.err.find("missing 3D model: R1\t") != std::string::npos);
    CHECK(lacking.err.find("no-such-model.step") != std::string::npos);

#ifndef _WIN32
    // Two at once into one folder (the GUI's side-by-side view): kicad-cli's
    // scratch file next to its output mustn't be shared.
    std::string a = (tmp / "a.glb").string(), b = (tmp / "b.glb").string();
    run(quote(KIGIT_BIN) + " --no-log -q --3d HEAD -o " + quote(a) + " -C " + dir + " & " +
                         quote(KIGIT_BIN) + " --no-log -q --3d HEAD~1 -o " + quote(b) + " -C " + dir +
                         " & wait");
    CHECK(read_text(a).substr(0, 4) == "glTF");
    CHECK(read_text(b).substr(0, 4) == "glTF");
    for (const auto& e : fs::directory_iterator(tmp.path()))
        CHECK(e.path().filename().string().find("tempfile") == std::string::npos);
#endif
}

TEST_CASE("--render: a picture of the board on disk, by kicad-cli") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string dir = quote((tmp / "board").string());
    if (!kigit::platform::find_kicad_cli()) {
        CHECK(run_kigit("--render -o x.png -C " + dir).code == 1); // says why
        return;
    }
    CHECK(run_kigit("--render -C " + dir).code == 1); // needs -o
    std::string png = (tmp / "pics/board.png").string();
    RunResult r = run_kigit("--render -o " + quote(png) + " -C " + dir);
    INFO("stderr: " << r.err);
    REQUIRE(r.code == 0);
    CHECK(r.out.find("board.png") != std::string::npos);
    CHECK(read_text(png).substr(1, 3) == "PNG");
}

TEST_CASE("kigit example: the example project's history, the same everywhere") {
    TempDir tmp;
    std::string dir = (tmp / "ex").string();
    RunResult made = run_kigit("example " + quote(dir));
    INFO("stderr: " << made.err);
    REQUIRE(made.code == 0);
    CHECK(made.out.find("hardware") != std::string::npos); // the project folder
    RunResult log = run("git -C " + quote(dir) + " log --format=%H%x20%s");
    CHECK(std::count(log.out.begin(), log.out.end(), '\n') == 6);
    // Fixed authors, UTC dates and no line-ending conversion: the same commits
    // for everyone, on every OS (the reviews name them). Pinned on purpose:
    // after changing the example (tools/make_example.py), update these.
    CHECK(log.out.find("First board") != std::string::npos);
    CHECK(run("git -C " + quote(dir) + " rev-list --max-parents=0 HEAD").out.substr(0, 40) == "791d17b7cb4fd78a351a15d45783b3ad195d3e11");
    CHECK(run("git -C " + quote(dir) + " rev-parse HEAD").out.substr(0, 40) == "b35493eae535b732fff2a2d632f584bf62b7b0d7");
    CHECK(!run("git -C " + quote(dir) + " status --porcelain").out.empty()); // an uncommitted change too
    // Commits named in the reviews are filled in.
    std::string review = read_text(tmp / "ex/hardware/reviews/3b6d1f22.md");
    CHECK(review.find("{{") == std::string::npos);
    CHECK(review.find(run("git -C " + quote(dir) + " rev-parse HEAD~3").out.substr(0, 40)) != std::string::npos);
    // Not over an existing project.
    CHECK(run_kigit("example " + quote(dir)).code == 1);
}

TEST_CASE("kigit example: a CRLF checkout (git on Windows) gives the same commits") {
    TempDir tmp;
    const fs::path src = fs::path(KIGIT_FIXTURES) / ".." / ".." / "examples";
    for (const auto& e : fs::recursive_directory_iterator(src)) {
        fs::path to = tmp / "crlf" / fs::relative(e.path(), src);
        if (e.is_directory()) { fs::create_directories(to); continue; }
        std::string text = read_text(e.path()), crlf;
        for (char c : text) crlf += c == '\n' ? std::string("\r\n") : std::string(1, c);
        std::ofstream(to, std::ios::binary) << crlf;
    }
    kigit::platform::set_env("KIGIT_EXAMPLES_DIR", (tmp / "crlf").string());
    RunResult made = run_kigit("example " + quote((tmp / "ex").string()));
    kigit::platform::set_env("KIGIT_EXAMPLES_DIR", "");
    INFO("stderr: " << made.err);
    REQUIRE(made.code == 0);
    CHECK(run("git -C " + quote((tmp / "ex").string()) + " rev-parse HEAD").out.substr(0, 40) ==
          "b35493eae535b732fff2a2d632f584bf62b7b0d7");
}

TEST_CASE("kigit uninstall: only an installed kigit, only its own files") {
    // A build folder isn't an install: nothing to do.
    RunResult build = run_kigit("uninstall --yes");
    CHECK(build.code == 1);
    CHECK(build.err.find("isn't an installed kigit") != std::string::npos);
    CHECK(fs::exists(KIGIT_BIN));
#ifndef _WIN32
    // An installed layout: <prefix>/bin/kigit, share/kigit, libexec/kigit,
    // in a folder (bin) that other programs share.
    TempDir tmp;
    const fs::path prefix = tmp / "prefix";
    fs::create_directories(prefix / "bin");
    fs::create_directories(prefix / "share" / "kigit" / "gui");
    fs::create_directories(prefix / "libexec" / "kigit");
    std::ofstream(prefix / "bin" / "other-tool") << "x";
    fs::copy_file(KIGIT_BIN, prefix / "bin" / "kigit");
    fs::permissions(prefix / "bin" / "kigit", fs::perms::owner_all);
    fs::create_directories(tmp / "state" / "kigit" / "log");  // the app folder, here
    kigit::platform::set_env("XDG_STATE_HOME", (tmp / "state").string());
    const std::string installed = quote((prefix / "bin" / "kigit").string());

    RunResult no = run("echo n | " + installed + " uninstall");
    CHECK(no.code == 1);
    CHECK(fs::exists(prefix / "bin" / "kigit"));  // asked, said no
    CHECK(no.err.find("the kigit program") != std::string::npos);  // says what each thing is
    CHECK(no.err.find("Your projects are not touched") != std::string::npos);
    CHECK(no.err.find("--purge deletes that too") != std::string::npos);
    fs::create_directories(tmp / "state" / "kigit" / "example");
    RunResult warned = run("echo n | " + installed + " uninstall --purge");
    CHECK(warned.err.find("WARNING: the example project") != std::string::npos);  // what --purge also takes
    CHECK(warned.err.find("session logs") != std::string::npos);
    CHECK(fs::exists(tmp / "state" / "kigit" / "example"));

    RunResult yes = run(installed + " uninstall --yes");
    INFO("stderr: " << yes.err);
    CHECK(yes.code == 0);
    CHECK(!fs::exists(prefix / "bin" / "kigit"));
    CHECK(!fs::exists(prefix / "share" / "kigit"));
    CHECK(!fs::exists(prefix / "libexec" / "kigit"));
    CHECK(fs::exists(prefix / "bin" / "other-tool"));  // the shared folders and what else is in them stay
    CHECK(fs::exists(prefix / "share"));
    CHECK(fs::exists(tmp / "state" / "kigit"));  // the app folder only with --purge

    fs::copy_file(KIGIT_BIN, prefix / "bin" / "kigit");
    fs::permissions(prefix / "bin" / "kigit", fs::perms::owner_all);
    fs::create_directories(prefix / "share" / "kigit");
    CHECK(run(installed + " uninstall --yes --purge").code == 0);
    CHECK(!fs::exists(tmp / "state" / "kigit"));
    CHECK(fs::exists(tmp / "state"));
    kigit::platform::set_env("XDG_STATE_HOME", "");
#endif
}

TEST_CASE("diff across the folder rename, as JSON on stdout") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());

    RunResult r = run_kigit("-n --json -o - -C " + board + " HEAD~3..HEAD");
    json d = parse(r);
    CHECK(r.err.find("moved or renamed") != std::string::npos); // hw/ -> board/
    CHECK(d["meta"]["old"]["subject"] == "v1: first board");
    CHECK(d["meta"]["old"]["hash"].get<std::string>().size() == 40); // full hash, for review anchors

    // PCB: R2 and a track moved; schematic: C1 added, R2's value changed.
    int moved = 0;
    for (const auto& n : d["nets"]) moved += n["moved"].get<int>();
    CHECK(moved == 3);
    bool c1_added = false, r2_value = false;
    for (const auto& s : d["schematic_diff"]["symbols"]) {
        if (s["ref_after"] == "C1" && s["status"] == "added") c1_added = true;
        if (s["ref_after"] == "R2")
            for (const auto& f : s["fields"]) r2_value |= f["field"] == "Value" && f["after"] == "4k7";
    }
    CHECK(c1_added);
    CHECK(r2_value);

    // Footprints and pours: R1's pads changed within the footprint; the GND
    // pour was only refilled, the VCC pour's outline was edited.
    bool r1_pads = false;
    for (const auto& f : d["footprints"]) r1_pads |= f["ref"] == "R1" && f["pads"] == true;
    CHECK(r1_pads);
    std::set<std::string> zone_kinds;
    for (const auto& z : d["zone_changes"]) zone_kinds.insert(z["net"].get<std::string>() + ":" + z["kind"].get<std::string>());
    CHECK(zone_kinds == std::set<std::string>{"GND:refilled", "VCC:outline"});
}

TEST_CASE("--silkscreen is opt-in") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());
    CHECK(parse(run_kigit("-n --json -o - -C " + board + " HEAD~3..HEAD"))["silk"].is_null());
    json with = parse(run_kigit("-n --json -o - --silkscreen -C " + board + " HEAD~3..HEAD"));
    REQUIRE(with["silk"].is_array());
    CHECK(with["silk"].size() > 0);
}

TEST_CASE("revisions given newest-first are swapped") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());
    json d = parse(run_kigit("-n --json -o - -C " + board + " HEAD..HEAD~3"));
    CHECK(d["meta"]["old"]["subject"] == "v1: first board");
    CHECK(d["meta"]["new"]["subject"] == "move project folder");
}

TEST_CASE("the HTML page goes to stdout with -o -") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    RunResult r = run_kigit("-n -o - -C " + quote((tmp / "board/demo.kicad_pcb").string()) + " HEAD~1..HEAD");
    REQUIRE(r.code == 0);
    CHECK(r.out.rfind("<!doctype html>", 0) == 0);
    CHECK(r.out.find("/*KIGIT_DATA*/") == std::string::npos); // data was filled in
}

TEST_CASE("--files compares two board files without git") {
    RunResult r = run_kigit("-n --json -o - --files " + quote(fixture("v1/demo.kicad_pcb").string()) + " " +
                        quote(fixture("v2/demo.kicad_pcb").string()));
    json d = parse(r);
    CHECK(d["meta"]["old"]["short"] == "v1");
    CHECK(d["meta"]["new"]["short"] == "v2");
}

TEST_CASE("errors: clear message, non-zero exit") {
    TempDir tmp;
    make_fixture_repo(tmp / "repo");
    std::string board = quote((tmp / "repo/board/demo.kicad_pcb").string());

    std::string out = quote((tmp / "out.html").string());
    RunResult bad_rev = run_kigit("-n -o " + out + " -C " + board + " nope..HEAD");
    CHECK(bad_rev.code == 1);
    CHECK(bad_rev.err.find("unknown revision 'nope'") != std::string::npos);

    // (A copy outside any git repo; tests/fixtures itself is inside kigit's repo.)
    write_text(tmp / "loose/demo.kicad_pcb", read_text(fixture("v1/demo.kicad_pcb")));
    RunResult no_repo = run_kigit("-n -o " + out + " -C " + quote((tmp / "loose").string()));
    CHECK(no_repo.code == 1);
    CHECK(no_repo.err.find("not in a git repository") != std::string::npos);

    RunResult bad_opt = run_kigit("--frobnicate");
    CHECK(bad_opt.code == 2);
}

}
