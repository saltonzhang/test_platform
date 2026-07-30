export function installOverflowTooltip() {
  const tooltip = document.createElement('div')
  tooltip.className = 'table-overflow-tooltip'
  document.body.appendChild(tooltip)

  const hide = () => { tooltip.style.display = 'none' }
  const show = (event: MouseEvent) => {
    const cell = (event.target as HTMLElement).closest<HTMLElement>('.el-table__cell .cell')
    if (!cell || cell.scrollWidth <= cell.clientWidth) {
      hide()
      return
    }
    const text = (cell.textContent || '').trim()
    if (!text) return
    const rect = cell.getBoundingClientRect()
    tooltip.textContent = text
    tooltip.style.display = 'block'
    tooltip.style.left = `${Math.min(rect.left, window.innerWidth - tooltip.offsetWidth - 12)}px`
    tooltip.style.top = `${Math.min(rect.bottom + 8, window.innerHeight - tooltip.offsetHeight - 12)}px`
  }

  document.addEventListener('mouseover', show)
  document.addEventListener('mouseout', hide)
  window.addEventListener('scroll', hide, true)
  return () => {
    document.removeEventListener('mouseover', show)
    document.removeEventListener('mouseout', hide)
    window.removeEventListener('scroll', hide, true)
    tooltip.remove()
  }
}
