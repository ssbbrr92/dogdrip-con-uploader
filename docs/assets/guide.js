const links = [...document.querySelectorAll('.sidebar nav a')];
const sections = links.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);

const observer = new IntersectionObserver(entries => {
  const current = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!current) return;
  links.forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${current.target.id}`));
}, { rootMargin: '-20% 0px -65%', threshold: [0, .2, .6] });

sections.forEach(section => observer.observe(section));

document.querySelectorAll('.faq details').forEach(item => {
  item.addEventListener('toggle', () => {
    if (!item.open) return;
    document.querySelectorAll('.faq details').forEach(other => {
      if (other !== item) other.open = false;
    });
  });
});
