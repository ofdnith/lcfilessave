// The full-screen viewer is global so any list can open it.
import type { ItemList } from './itemlist.svelte';
import type { View } from './types';

export const viewer = $state({
  list: null as ItemList | null,
  index: -1,
  view: 'library' as View,
});

export function openViewer(list: ItemList, index: number, view: View): void {
  viewer.list = list;
  viewer.index = index;
  viewer.view = view;
}

export function closeViewer(): void {
  viewer.list = null;
  viewer.index = -1;
}
