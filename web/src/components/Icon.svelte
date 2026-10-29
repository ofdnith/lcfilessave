<script lang="ts" module>
  // Stroke icons, 24px grid. Paths are hand-drawn to keep the bundle dependency-free.
  const paths = {
    library: 'M4 5h16v14H4z M4 15l4.5-4.5 4 4 2.5-2.5L20 17 M15.5 9.5a1.5 1.5 0 1 0 0-.01',
    inbox: 'M4 13l2.5-8h11l2.5 8v6H4z M4 13h5l1 2.5h4l1-2.5h5',
    trash: 'M5 7h14 M10 4h4 M7 7l1 13h8l1-13 M10.5 11v5 M13.5 11v5',
    upload: 'M12 16V4 M7 9l5-5 5 5 M5 20h14',
    settings:
      'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 13.5l1.6 1-2 3.4-1.8-.7a7 7 0 0 1-1.7 1l-.3 1.8h-4l-.3-1.8a7 7 0 0 1-1.7-1l-1.8.7-2-3.4 1.6-1a7 7 0 0 1 0-3l-1.6-1 2-3.4 1.8.7a7 7 0 0 1 1.7-1L10 2h4l.3 1.8a7 7 0 0 1 1.7 1l1.8-.7 2 3.4-1.6 1a7 7 0 0 1 0 3z',
    drive: 'M3 14h18v5H3z M5 14l2-9h10l2 9 M17 16.5h.01',
    phone: 'M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z M11 18h2',
    search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M20 20l-4.6-4.6',
    close: 'M6 6l12 12 M18 6L6 18',
    left: 'M15 5l-7 7 7 7',
    right: 'M9 5l7 7-7 7',
    up: 'M5 15l7-7 7 7',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    star: 'M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z',
    download: 'M12 4v12 M7 11l5 5 5-5 M5 20h14',
    restore: 'M4 12a8 8 0 1 0 2.4-5.7 M4 4v4.5h4.5',
    info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 11v5 M12 8h.01',
    play: 'M8 5.5v13l10.5-6.5z',
    live: 'M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12z M12 2v1 M12 21v1 M2 12h1 M21 12h1 M4.9 4.9l.7.7 M18.4 18.4l.7.7 M4.9 19.1l.7-.7 M18.4 5.6l.7-.7',
    doc: 'M7 3h7l5 5v13H7z M14 3v5h5 M10 13h6 M10 17h6',
    audio: 'M9 18V6l10-2v12 M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z M19 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
    file: 'M7 3h7l5 5v13H7z M14 3v5h5',
    video: 'M4 6h11v12H4z M15 10l5-3v10l-5-3z',
    photo: 'M4 5h16v14H4z M4 15l4.5-4.5 4 4 2.5-2.5L20 17',
    zap: 'M13 3L5 13.5h6L10 21l9-11h-6z',
    select: 'M5 5h14v14H5z M8.5 12l2.5 2.5 4.5-5',
    alert: 'M12 4l9 16H3z M12 10v4 M12 17h.01',
    open: 'M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6',
    undo: 'M9 14L4 9l5-5 M4 9h10a6 6 0 0 1 0 12h-3',
    logout: 'M15 4h4v16h-4 M10 16l-4-4 4-4 M6 12h10',
    shield: 'M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6z M9 12l2 2 4-4',
    folder: 'M3 6h6l2 2h10v11H3z',
    plus: 'M12 5v14 M5 12h14',
    server: 'M4 4h16v6H4z M4 14h16v6H4z M8 7h.01 M8 17h.01',
    share: 'M12 15V4 M8 8l4-4 4 4 M6 12H5v8h14v-8h-1',
    map: 'M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z M12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
    album: 'M4 7h16v13H4z M6.5 4h11 M4 16l4.5-4 3.5 3 2.5-2L20 17.5',
    albumAdd: 'M4 7h12v13H4z M6.5 4h9 M19 9v6 M16 12h6',
    copy: 'M9 9h11v11H9z M5 15H4V4h11v1',
    key: 'M14.5 9.5a4.5 4.5 0 1 0-4 4.5l1.5 1.5h2v2h2v2h3v-3l-4.5-4.5a4.5 4.5 0 0 0 0-2.5z M8.5 8.5h.01',
    bell: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z M10 20.5a2 2 0 0 0 4 0',
    edit: 'M4 20h4L19 9l-4-4L4 16z M13.5 6.5l4 4',
    calendar: 'M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4',
    zoom: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M20 20l-4.6-4.6 M10.5 8v5 M8 10.5h5',
    lock: 'M6 11h12v10H6z M8.5 11V8a3.5 3.5 0 0 1 7 0v3',
  } as const;
  export type IconName = keyof typeof paths;
</script>

<script lang="ts">
  let { name, size = 22, fill = false }: { name: IconName; size?: number; fill?: boolean } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill={fill ? 'currentColor' : 'none'}
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={paths[name]} />
</svg>
