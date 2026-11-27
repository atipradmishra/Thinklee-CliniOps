(() => {
  const search = document.getElementById('home-dashboard-search');
  if (search) search.addEventListener('input', () => {
    const term = search.value.trim().toLocaleLowerCase();
    const cards = [...document.querySelectorAll('[data-dashboard-name]')];
    cards.forEach(card => { card.hidden = !card.dataset.dashboardName.toLocaleLowerCase().includes(term); });
    document.getElementById('home-no-results').hidden = cards.some(card => !card.hidden);
  });
  document.getElementById('home-tour')?.addEventListener('click', () => {
    if (window.ThinkleeTour) window.ThinkleeTour.start();
    else window.location.assign('/steps');
  });
  document.querySelectorAll('.home-page time[datetime]').forEach(element => {
    const date = new Date(element.dateTime);
    if (!Number.isNaN(date.valueOf())) {
      element.textContent = new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'}).format(date);
      element.title = date.toISOString();
    }
  });
})();
