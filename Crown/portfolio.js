(function(){
  // ====== CONFIG ======
  const FOLDER = "images/Collection/Slides/";
  const THUMB_FOLDER = "images/Collection/Thumbs/";
  const BASENAME = "slide-";
  const EXT = "webp";
  const COUNT = 44;
  const AUTOPLAY_MS = 4500;

  const slidesTrack = document.getElementById("slidesTrack");
  const statusEl = document.getElementById("sliderStatus");
  const galleryEl = document.getElementById("portfolioGallery");

  const lightbox = document.getElementById("lightbox");
  const lightboxImg = document.getElementById("lightboxImg");
  const lightboxCaption = document.getElementById("lightboxCaption");
  const lightboxClose = document.getElementById("lightboxClose");
  const lightboxBackdrop = document.getElementById("lightboxBackdrop");

  const fullImages = Array.from({ length: COUNT }, (_, i) => `${FOLDER}${BASENAME}${i + 1}.${EXT}`);
  const thumbImages = Array.from({ length: COUNT }, (_, i) => `${THUMB_FOLDER}${BASENAME}${i + 1}.${EXT}`);
  let idx = 0;
  let autoplay = null;

  function updateStatus() {
    if (!statusEl) return;
    statusEl.textContent = fullImages.length ? `${idx + 1} / ${fullImages.length}` : "";
  }

  function openLightbox(url, label) {
    if (!lightbox) return;
    lightboxImg.src = url;
    lightboxCaption.textContent = label || "";
    lightbox.classList.remove("hidden");
    lightbox.setAttribute("aria-hidden", "false");
    stopAutoplay();
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.classList.add("hidden");
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImg.removeAttribute("src");
    startAutoplay();
  }

  function renderSlide() {
    if (!slidesTrack) return;
    slidesTrack.innerHTML = "";
    const fig = document.createElement("figure");
    fig.className = "slide active";

    const img = document.createElement("img");
    img.src = fullImages[idx];
    img.alt = `Portfolio image ${idx + 1}`;
    img.draggable = false;

    img.style.cursor = "default";
    img.style.pointerEvents = "none";

    fig.appendChild(img);
    slidesTrack.appendChild(fig);

    updateStatus();
  }

  function startAutoplay() {
    stopAutoplay();
    autoplay = setInterval(() => {
      idx = (idx + 1) % fullImages.length;
      renderSlide();
    }, AUTOPLAY_MS);
  }

  function stopAutoplay() {
    if (autoplay) clearInterval(autoplay);
    autoplay = null;
  }

  function renderGallery() {
    if (!galleryEl) return;
    galleryEl.innerHTML = "";
    const frag = document.createDocumentFragment();

    fullImages.forEach((url, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gallery-thumb";
      btn.setAttribute("aria-label", `Open image ${i + 1}`);

      const img = document.createElement("img");
      img.alt = `Portfolio thumbnail ${i + 1}`;
      img.loading = "lazy";
      img.decoding = "async";
      img.dataset.src = thumbImages[i] || url;

      btn.appendChild(img);
      btn.addEventListener("click", () => openLightbox(url, `Image ${i + 1} / ${fullImages.length}`));
      frag.appendChild(btn);
    });

    galleryEl.appendChild(frag);

    const io = new IntersectionObserver((entries, obs) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const img = entry.target;
        const realSrc = img.dataset.src;
        if (realSrc) {
          img.src = realSrc;
          delete img.dataset.src;
        }
        obs.unobserve(img);
      }
    }, { rootMargin: "350px 0px" });

    galleryEl.querySelectorAll("img[data-src]").forEach(img => io.observe(img));
  }

  if (lightboxClose) lightboxClose.addEventListener("click", closeLightbox);
  if (lightboxBackdrop) lightboxBackdrop.addEventListener("click", closeLightbox);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && lightbox && !lightbox.classList.contains("hidden")) closeLightbox();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAutoplay();
    else startAutoplay();
  });

  if (!fullImages.length) {
    if (statusEl) statusEl.textContent = "No images found.";
    return;
  }

  renderSlide();
  renderGallery();
  startAutoplay();
})();
