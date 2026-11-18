#include "parts/source.hpp"

#include <thread>

namespace kigit::parts {

net::HttpResponse Source::send(const net::HttpRequest& rq) {
    if (calls_ > 0) {
        auto wait = pace_ - (std::chrono::steady_clock::now() - last_);
        if (wait > std::chrono::milliseconds(0)) std::this_thread::sleep_for(wait);
    }
    ++calls_;
    net::HttpResponse r = http_(rq);
    last_ = std::chrono::steady_clock::now();
    return r;
}

} // namespace kigit::parts
