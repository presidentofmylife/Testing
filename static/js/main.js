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
