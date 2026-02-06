(() => {
  // ====== CONFIG ======
  // IMPORTANT: This assumes your files are named exactly:
  // images/Collection/Slides/slide-1.jpg ... slide-44.jpg
  const FOLDER = "images/Collection/Slides/";
  const BASENAME = "slide-";
  const EXT = "webp";          // Change to "png" if your slides are png
  const COUNT = 44;           // You said you currently have 44 images
  const AUTOPLAY_MS = 4500;   // slideshow speed

  // ====== ELEMENTS ======
  const slidesTrack = document.getElementById("slidesTrack");
  const statusEl = document.getElementById("sliderStatus");
  const galleryEl = document.getElementById("portfolioGallery");

  const lightbox = document.getElementById("lightbox");
  const lightboxImg = document.getElementById("lightboxImg");
  const lightboxCaption = document.getElementById("lightboxCaption");
  const lightboxClose = document.getElementById("lightboxClose");
  const lightboxBackdrop = document.getElementById("lightboxBackdrop");

  // ====== STATE ======
  const images = Array.from({ length: COUNT }, (_, i) => `${FOLDER}${BASENAME}${i + 1}.${EXT}`);
  let idx = 0;
  let autoplay = null;

  // ====== HELPERS ======
  function updateStatus() {
    statusEl.textContent = images.length ? `${idx + 1} / ${images.length}` : "";
  }

  function openLightbox(url, label) {
    lightboxImg.src = url;
    lightboxCaption.textContent = label || "";
    lightbox.classList.remove("hidden");
    lightbox.setAttribute("aria-hidden", "false");
    stopAutoplay();
  }

  function closeLightbox() {
    lightbox.classList.add("hidden");
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImg.removeAttribute("src");
    startAutoplay();
  }

  function renderSlide() {
    slidesTrack.innerHTML = "";
    const fig = document.createElement("figure");
    fig.className = "slide active";

    const img = document.createElement("img");
    img.src = images[idx];
    img.alt = `Portfolio image ${idx + 1}`;
    img.draggable = false;

    // slideshow is NOT interactable
    img.style.cursor = "default";
    img.style.pointerEvents = "none";

    fig.appendChild(img);
    slidesTrack.appendChild(fig);

    updateStatus();
  }

  function startAutoplay() {
    stopAutoplay();
    autoplay = setInterval(() => {
      idx = (idx + 1) % images.length;
      renderSlide();
    }, AUTOPLAY_MS);
  }

  function stopAutoplay() {
    if (autoplay) clearInterval(autoplay);
    autoplay = null;
  }

  // ====== GALLERY RENDER (PERFORMANCE FRIENDLY) ======
  function renderGallery() {
    galleryEl.innerHTML = "";

    // Use a document fragment to avoid layout thrash
    const frag = document.createDocumentFragment();

    images.forEach((url, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gallery-thumb";
      btn.setAttribute("aria-label", `Open image ${i + 1}`);

      const img = document.createElement("img");
      img.alt = `Portfolio thumbnail ${i + 1}`;

      // Lazy load (native)
      img.loading = "lazy";
      img.decoding = "async";

      // We'll set src via IntersectionObserver for even smoother scrolling
      img.dataset.src = url;

      btn.appendChild(img);

      btn.addEventListener("click", () => {
        openLightbox(url, `Image ${i + 1} / ${images.length}`);
      });

      frag.appendChild(btn);
    });

    galleryEl.appendChild(frag);

    // IntersectionObserver: only assign real src when near viewport
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

  // ====== LIGHTBOX EVENTS ======
  lightboxClose.addEventListener("click", closeLightbox);
  lightboxBackdrop.addEventListener("click", closeLightbox);

  // Close on ESC
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !lightbox.classList.contains("hidden")) closeLightbox();
  });

  // Pause autoplay when tab not visible (saves CPU / avoids weird jumps)
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAutoplay();
    else startAutoplay();
  });

  // ====== INIT ======
  if (!images.length) {
    statusEl.textContent = "No images found.";
    return;
  }

  renderSlide();
  renderGallery();
  startAutoplay();
})();
