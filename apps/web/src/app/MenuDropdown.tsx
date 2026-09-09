// Primitive de menu deroulant reutilisee par chaque categorie de la barre de menus (cdc §4).

import { useEffect, useRef, useState } from 'react'

export interface MenuDropdownItem {
  label: string
  onClick?: () => void
  disabled?: boolean
}

interface MenuDropdownProps {
  label: string
  items: MenuDropdownItem[]
  hint?: string
  disabled?: boolean
}

export function MenuDropdown({ label, items, hint, disabled }: MenuDropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [open])

  return (
    <div className="menu-dropdown" ref={ref}>
      <button type="button" className="menu-item" disabled={disabled} onClick={() => setOpen((o) => !o)}>
        {label}
      </button>
      {open && (
        <div className="menu-dropdown-list">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              className="menu-dropdown-item"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false)
                item.onClick?.()
              }}
            >
              {item.label}
            </button>
          ))}
          {hint && <div className="menu-dropdown-hint">{hint}</div>}
        </div>
      )}
    </div>
  )
}
