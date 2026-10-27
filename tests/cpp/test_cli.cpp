// End-to-end tests: the real kigit binary on the fixture repo.
#include "helpers.hpp"

#include <doctest/doctest.h>
#include <nlohmann/json.hpp>

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

TEST_CASE("diff across the folder rename, as JSON on stdout") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());

    RunResult r = run_kigit("-n --json -o - -C " + board + " HEAD~3..HEAD");
    json d = parse(r);
    CHECK(r.err.find("moved or renamed") != std::string::npos); // hw/ -> board/
    CHECK(d["meta"]["old"]["subject"] == "v1: first board");

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

    RunResult bad_rev = run_kigit("-n -o /dev/null -C " + board + " nope..HEAD");
    CHECK(bad_rev.code == 1);
    CHECK(bad_rev.err.find("unknown revision 'nope'") != std::string::npos);

    // (A copy outside any git repo; tests/fixtures itself is inside kigit's repo.)
    write_text(tmp / "loose/demo.kicad_pcb", read_text(fixture("v1/demo.kicad_pcb")));
    RunResult no_repo = run_kigit("-n -o /dev/null -C " + quote((tmp / "loose").string()));
    CHECK(no_repo.code == 1);
    CHECK(no_repo.err.find("not in a git repository") != std::string::npos);

    RunResult bad_opt = run_kigit("--frobnicate");
    CHECK(bad_opt.code == 2);
}

}
