(() => {
  const revealEls = document.querySelectorAll('[data-reveal]');
  if (revealEls.length) {
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.16 }
    );

    revealEls.forEach((el) => obs.observe(el));
  }

  const carousels = document.querySelectorAll('[data-carousel]');
  carousels.forEach((carousel) => {
    const slides = Array.from(carousel.querySelectorAll('[data-carousel-slide]'));
    const dots = Array.from(carousel.querySelectorAll('[data-carousel-dot]'));
    const cards = Array.from(carousel.querySelectorAll('[data-carousel-card]'));
    const prevBtn = carousel.querySelector('[data-carousel-prev]');
    const nextBtn = carousel.querySelector('[data-carousel-next]');

    if (!slides.length) return;

    let activeIndex = slides.findIndex((slide) => slide.classList.contains('is-active'));
    if (activeIndex < 0) activeIndex = 0;
    let autoRotateId;

    const renderCarousel = (nextIndex) => {
      activeIndex = (nextIndex + slides.length) % slides.length;

      slides.forEach((slide, index) => {
        slide.classList.toggle('is-active', index === activeIndex);
      });

      dots.forEach((dot, index) => {
        const isActive = index === activeIndex;
        dot.classList.toggle('is-active', isActive);
        dot.setAttribute('aria-pressed', String(isActive));
      });

      cards.forEach((card, index) => {
        const isActive = index === activeIndex;
        card.classList.toggle('is-active', isActive);
        card.setAttribute('aria-pressed', String(isActive));
      });
    };

    const startAutoRotate = () => {
      clearInterval(autoRotateId);
      autoRotateId = window.setInterval(() => {
        renderCarousel(activeIndex + 1);
      }, 5200);
    };

    prevBtn?.addEventListener('click', () => {
      renderCarousel(activeIndex - 1);
      startAutoRotate();
    });

    nextBtn?.addEventListener('click', () => {
      renderCarousel(activeIndex + 1);
      startAutoRotate();
    });

    dots.forEach((dot, index) => {
      dot.addEventListener('click', () => {
        renderCarousel(index);
        startAutoRotate();
      });
    });

    cards.forEach((card, index) => {
      card.addEventListener('click', () => {
        renderCarousel(index);
        startAutoRotate();
      });
    });

    carousel.addEventListener('mouseenter', () => clearInterval(autoRotateId));
    carousel.addEventListener('mouseleave', startAutoRotate);

    renderCarousel(activeIndex);
    startAutoRotate();
  });

  const zoneData = {
    neck: {
      title: 'منطقة الرقبة',
      text: 'جلسات فك انضغاط خفيفة مع تمارين دعم عميقة لثبات الفقرات العنقية.'
    },
    upper: {
      title: 'أعلى الظهر',
      text: 'نخفف الشد بين لوحي الكتف ونحسن الميكانيكا التنفسية مع التمدد الموجه.'
    },
    lumbar: {
      title: 'المنطقة القطنية',
      text: 'تركيز على تثبيت القطنية وتقوية السلسلة الخلفية لتقليل الانتكاس.'
    },
    core: {
      title: 'الجذع',
      text: 'تدريبات تحمل محورية متدرجة لتحسين التحكم الحركي والدعم الداخلي.'
    },
    pelvis: {
      title: 'الحوض',
      text: 'تحسين اصطفاف الحوض وتوزيع الحمل على الورك لتخفيف الألم الممتد.'
    }
  };

  const zoneTitle = document.getElementById('zone-title');
  const zoneText = document.getElementById('zone-text');
  const zoneButtons = document.querySelectorAll('.zone-btn');
  const zoneBlocks = document.querySelectorAll('.muscle-zone');

  const activateZone = (zoneName) => {
    if (!zoneData[zoneName] || !zoneTitle || !zoneText) return;

    zoneTitle.textContent = zoneData[zoneName].title;
    zoneText.textContent = zoneData[zoneName].text;

    zoneButtons.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.zoneTarget === zoneName);
    });

    zoneBlocks.forEach((zone) => {
      zone.classList.toggle('active', zone.dataset.zone === zoneName);
    });
  };

  zoneButtons.forEach((btn) => {
    btn.addEventListener('click', () => activateZone(btn.dataset.zoneTarget));
  });

  zoneBlocks.forEach((zone) => {
    zone.addEventListener('mouseenter', () => activateZone(zone.dataset.zone));
    zone.addEventListener('click', () => activateZone(zone.dataset.zone));
  });

  const startInput = document.getElementById('start_time');
  const endInput = document.getElementById('end_time');
  if (startInput && endInput) {
    startInput.addEventListener('change', () => {
      if (startInput.value) {
        endInput.min = startInput.value;
        if (endInput.value && endInput.value <= startInput.value) {
          endInput.value = '';
        }
      }
    });
  }
})();
