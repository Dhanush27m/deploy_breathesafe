// Central SVG icon library — no emoji, no external dependencies
// All icons are 24x24 viewBox, strokeWidth=1.75, rounded caps

const base = { xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 24 24', fill: 'none',
                stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round' }

const I = ({ d, children, size = 18, className = '' }) => (
  <svg {...base} width={size} height={size} className={className}>
    {d ? <path d={d} /> : children}
  </svg>
)

export const IconHome          = p => <I {...p}><rect x="3" y="9" width="18" height="13" rx="2"/><polyline points="3 9 12 2 21 9"/></I>
export const IconBarChart      = p => <I {...p}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></I>
export const IconTrendingUp    = p => <I {...p} d="M23 6l-9.5 9.5-5-5L1 18"/>
export const IconWind          = p => <I {...p}><path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2"/><path d="M9.6 4.6A2 2 0 1 1 11 8H2"/><path d="M12.6 19.4A2 2 0 1 0 14 16H2"/></I>
export const IconActivity      = p => <I {...p} d="M22 12h-4l-3 9L9 3l-3 9H2"/>
export const IconMap           = p => <I {...p}><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></I>
export const IconBell          = p => <I {...p}><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></I>
export const IconUser          = p => <I {...p}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></I>
export const IconSettings      = p => <I {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></I>
export const IconLeaf          = p => <I {...p} d="M17 8C8 10 5.9 16.17 3.82 19.5c-.55.86.21 1.83 1.17 1.5C7 20 9 19 12 19c6 0 10-5 10-11V3a1 1 0 0 0-1.7-.71C18.5 4.07 17.5 6 17 8z"/>
export const IconCheck         = p => <I {...p} d="M20 6L9 17l-5-5"/>
export const IconX             = p => <I {...p} d="M18 6L6 18M6 6l12 12"/>
export const IconAlertTriangle = p => <I {...p}><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></I>
export const IconInfo          = p => <I {...p}><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></I>
export const IconSearch        = p => <I {...p}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></I>
export const IconLogOut        = p => <I {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></I>
export const IconRefreshCw     = p => <I {...p}><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></I>
export const IconMapPin        = p => <I {...p}><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></I>
export const IconNavigation    = p => <I {...p} d="M3 11l19-9-9 19-2-8-8-2z"/>
export const IconClock         = p => <I {...p}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></I>
export const IconCalendar      = p => <I {...p}><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></I>
export const IconFilter        = p => <I {...p} d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/>
export const IconEdit          = p => <I {...p}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></I>
export const IconTrash         = p => <I {...p}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></I>
export const IconChevronRight  = p => <I {...p} d="M9 18l6-6-6-6"/>
export const IconChevronDown   = p => <I {...p} d="M6 9l6 6 6-6"/>
export const IconArrowRight    = p => <I {...p} d="M5 12h14M12 5l7 7-7 7"/>
export const IconPlus          = p => <I {...p} d="M12 5v14M5 12h14"/>
export const IconShield        = p => <I {...p} d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
export const IconHeart         = p => <I {...p} d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
export const IconDroplet       = p => <I {...p} d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>
export const IconSun           = p => <I {...p}><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></I>
export const IconEye           = p => <I {...p}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></I>
export const IconLungs         = p => <I {...p}><path d="M12 6V2"/><path d="M12 6C8 6 4 9 4 14c0 3 2 5 4 6"/><path d="M12 6c4 0 8 3 8 8 0 3-2 5-4 6"/><path d="M8 20c0 0-1-1-1-3s1-3 1-3"/><path d="M16 20c0 0 1-1 1-3s-1-3-1-3"/></I>
export const IconFlask         = p => <I {...p}><path d="M9 3h6v8l3.5 7A1 1 0 0 1 17.6 20H6.4a1 1 0 0 1-.9-1.45L9 11V3z"/><line x1="6" y1="8" x2="18" y2="8"/></I>
export const IconCpu           = p => <I {...p}><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></I>
export const IconRoute         = p => <I {...p}><circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/></I>
export const IconLayers        = p => <I {...p}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></I>
export const IconSmoke         = p => <I {...p}><path d="M8 8c0-2 2-4 4-4s4 2 4 4"/><path d="M4 12h16"/><path d="M4 16c0 2 2 4 4 4"/><path d="M16 16c0 2 2 4 4 4"/></I>
export const IconMail          = p => <I {...p}><rect x="2" y="4" width="20" height="16" rx="2"/><polyline points="2,4 12,13 22,4"/></I>
