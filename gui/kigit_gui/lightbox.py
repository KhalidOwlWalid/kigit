"""Clicking a picture in a review, note or discussion shows it full size: a
dark overlay with the picture as big as it fits, its name, and a link to
open it in a new tab. Click anywhere or press Esc to close. Pictures that
are links themselves stay links. Used in the GUI and on the Reviews page
(plain JS and CSS, no libraries).
"""

# `scope`: the CSS selector of the rendered Markdown the pictures are in.
_TEMPLATE = """
<style>
#kigit-lightbox { position: fixed; inset: 0; z-index: 10000; display: none; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px; background: rgba(5, 7, 10, .88); cursor: zoom-out;
  padding: 24px; }
#kigit-lightbox.open { display: flex; }
#kigit-lightbox img { max-width: 96vw; max-height: calc(100vh - 90px); object-fit: contain; border-radius: 6px;
  box-shadow: 0 10px 40px rgba(0,0,0,.6); background: #fff1; }
#kigit-lightbox .lb-bar { display: flex; gap: 14px; align-items: center; color: #c7ced8;
  font: 13px system-ui, sans-serif; }
#kigit-lightbox .lb-bar a { color: #e8b84d; text-decoration: none; cursor: pointer; }
#kigit-lightbox a.lb-open::after { content: " ↗" !important; color: inherit !important; font-size: inherit !important; }
%%SCOPE%% img { cursor: zoom-in; }
</style>
<div id="kigit-lightbox" role="dialog" aria-label="Picture" aria-hidden="true">
  <img alt="">
  <div class="lb-bar"><span class="lb-name"></span><a class="lb-open" target="_blank" rel="noopener">Open in new tab</a>
    <span>· click or Esc to close</span></div>
</div>
<script>
(() => {
  const box = document.getElementById("kigit-lightbox"), img = box.querySelector("img");
  const name = box.querySelector(".lb-name"), open = box.querySelector(".lb-open");
  const close = () => { box.classList.remove("open"); box.setAttribute("aria-hidden", "true"); img.src = ""; };
  document.addEventListener("click", (e) => {
    const pic = e.target.closest && e.target.closest("%%SCOPE%% img");
    if (pic && !pic.closest("a")) {
      e.preventDefault();
      e.stopPropagation();
      img.src = pic.currentSrc || pic.src;
      const alt = pic.getAttribute("alt") || "";
      const file = decodeURIComponent((pic.getAttribute("src") || "").split("/").pop().split("?")[0]);
      name.textContent = alt || (file.startsWith("data:") ? "" : file);
      open.href = pic.src;
      open.style.display = pic.src.startsWith("data:") ? "none" : "";
      box.classList.add("open");
      box.setAttribute("aria-hidden", "false");
      return;
    }
    if (box.classList.contains("open") && !e.target.closest(".lb-open")) close();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && box.classList.contains("open")) close(); });
})();
</script>
"""


def html(scope: str) -> str:
    """The lightbox for pictures inside `scope` (a CSS selector)."""
    return _TEMPLATE.replace("%%SCOPE%%", scope)
