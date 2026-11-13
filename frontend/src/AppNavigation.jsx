import { useEffect, useRef, useState } from 'react'
import './AppNavigation.css'

const icons = {
  today: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18m-13 5h3" /></>,
  generate: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 15h8m-4-4v8" /></>,
  saved: <><path d="M5 4h14v17l-7-4-7 4zM9 8h6" /></>,
  custom: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18M7 16h10m-2-2 2 2-2 2" /></>,
  'custom-saved': <><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3zM8 12h8m-8 3h5" /></>,
  profiles: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="9" cy="6" r="2" /><circle cx="15" cy="12" r="2" /><circle cx="9" cy="18" r="2" /></>,
}
const groups = [
  { label: 'Daily journals', ids: ['today', 'generate', 'saved'] },
  { label: 'Date ranges', ids: ['custom', 'custom-saved'] },
  { label: 'Strategies', ids: ['profiles'] },
]

function Icon({ children }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
}

function PageLinks({ pages, activePage, unsavedPages, busy, onSelect }) {
  return <nav className="app-navigation" aria-label="Journal pages">
    {groups.map(group => <div className="app-nav-group" key={group.label}>
      <p className="app-nav-group-label">{group.label}</p>
      {group.ids.map(id => {
        const page = pages.find(item => item.id === id)
        return <button key={id} type="button" className="app-nav-link"
          aria-current={activePage === id ? 'page' : undefined}
          aria-controls={`${id}-panel`} disabled={busy} onClick={() => onSelect(id)}>
          <Icon>{icons[id]}</Icon>
          <span className="app-nav-label">{page.label}
            {unsavedPages.includes(id) && <small className="app-nav-unsaved">Unsaved changes</small>}
          </span>
        </button>
      })}
    </div>)}
    {busy && <p className="app-nav-busy" role="status">Please wait for the current action to finish.</p>}
  </nav>
}

export default function AppNavigation({ pages, activePage, unsavedPages, busy, onSelect }) {
  const dialogRef = useRef(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const selected = pages.find(page => page.id === activePage)

  useEffect(() => {
    if (!menuOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const desktop = window.matchMedia('(min-width: 1101px)')
    const closeOnDesktop = () => {
      if (desktop.matches) dialogRef.current?.close()
    }
    desktop.addEventListener('change', closeOnDesktop)
    return () => {
      document.body.style.overflow = previousOverflow
      desktop.removeEventListener('change', closeOnDesktop)
    }
  }, [menuOpen])

  const navigationProps = { pages, activePage, unsavedPages, busy, onSelect }

  function openMenu() {
    dialogRef.current.showModal()
    setMenuOpen(true)
    dialogRef.current.querySelector('[aria-current="page"]:not(:disabled)')?.focus()
  }

  function selectMobilePage(page) {
    dialogRef.current.close()
    onSelect(page)
    requestAnimationFrame(() => document.getElementById(`${page}-panel`)?.focus({ preventScroll: true }))
  }

  return <>
    <aside className="app-sidebar">
      <div className="app-sidebar-heading">Workspace</div>
      <PageLinks {...navigationProps} />
    </aside>
    <header className="app-mobile-bar">
      <button type="button" className="app-menu-toggle" aria-label="Open navigation menu"
        aria-haspopup="dialog" aria-controls="app-menu" aria-expanded={menuOpen} onClick={openMenu}>
        <Icon><path d="M4 6h16M4 12h16M4 18h16" /></Icon>
        <span>Menu</span>
      </button>
      <span className="app-mobile-title">{selected.label}</span>
    </header>
    <dialog id="app-menu" className="app-menu" ref={dialogRef} aria-labelledby="app-menu-heading"
      onClose={() => setMenuOpen(false)}
      onClick={event => {
        if (event.target !== event.currentTarget) return
        const bounds = event.currentTarget.getBoundingClientRect()
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
          event.currentTarget.close()
        }
      }}>
      <div className="app-menu-heading">
        <span id="app-menu-heading">Workspace</span>
        <button type="button" className="app-menu-close" aria-label="Close navigation menu" onClick={() => dialogRef.current.close()}>
          <Icon><path d="m6 6 12 12M18 6 6 18" /></Icon>
        </button>
      </div>
      <PageLinks {...navigationProps} onSelect={selectMobilePage} />
    </dialog>
  </>
}
