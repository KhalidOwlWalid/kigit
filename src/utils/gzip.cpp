#include "utils/gzip.hpp"

#include <miniz.h>

namespace kigit::gzip {

std::optional<std::string> gunzip(const std::string& gz) {
    // The gzip header (RFC 1952): magic, method 8 (deflate), flags, then optional fields.
    const auto* p = reinterpret_cast<const unsigned char*>(gz.data());
    size_t n = gz.size(), at = 10;
    if (n < 18 || p[0] != 0x1f || p[1] != 0x8b || p[2] != 8) return std::nullopt;
    unsigned flags = p[3];
    if (flags & 4) { // extra field
        if (at + 2 > n) return std::nullopt;
        at += 2 + (p[at] | (p[at + 1] << 8));
    }
    for (unsigned f : {8u, 16u}) // file name, comment: zero-terminated
        if (flags & f) {
            while (at < n && p[at]) ++at;
            ++at;
        }
    if (flags & 2) at += 2; // header CRC
    if (at >= n) return std::nullopt;

    mz_stream s{};
    if (mz_inflateInit2(&s, -MZ_DEFAULT_WINDOW_BITS) != MZ_OK) return std::nullopt; // raw deflate
    s.next_in = p + at;
    s.avail_in = static_cast<unsigned int>(n - at);
    std::string out;
    char buf[1 << 16];
    int status = MZ_OK;
    while (status == MZ_OK) {
        s.next_out = reinterpret_cast<unsigned char*>(buf);
        s.avail_out = sizeof buf;
        status = mz_inflate(&s, MZ_NO_FLUSH);
        out.append(buf, sizeof buf - s.avail_out);
        if (status == MZ_BUF_ERROR && s.avail_in == 0) break; // cut short
    }
    mz_inflateEnd(&s);
    if (status != MZ_STREAM_END) return std::nullopt;
    return out;
}

} // namespace kigit::gzip
