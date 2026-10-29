<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import { plural } from '../lib/format';

  let { count, onclear, children }: { count: number; onclear: () => void; children: Snippet } = $props();
</script>

<div class="selbar" role="toolbar" aria-label="Ações da seleção">
  <button class="icon-btn" onclick={onclear} aria-label="Cancelar seleção"><Icon name="close" size={20} /></button>
  <span class="count num">{count ? plural(count, 'selecionado', 'selecionados') : 'Toque para selecionar'}</span>
  <div class="acts">{@render children()}</div>
</div>

<style>
  .selbar {
    position: fixed;
    z-index: 40;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(var(--sab) + 18px);
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 8px 6px 6px;
    border-radius: 999px;
    background: var(--raised);
    border: 1px solid var(--line);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
    max-width: calc(100vw - 24px);
    animation: up 0.18s var(--ease);
  }
  @keyframes up {
    from {
      transform: translate(-50%, 20px);
      opacity: 0;
    }
  }
  .count {
    font-weight: 600;
    font-size: 14px;
    white-space: nowrap;
    padding-right: 4px;
  }
  .acts {
    display: flex;
    gap: 6px;
  }
  @media (min-width: 900px) {
    .selbar {
      left: calc(50% + var(--sidebar) / 2);
    }
  }
  @media (max-width: 899px) {
    .selbar {
      bottom: calc(var(--sab) + var(--tabbar) + 12px);
    }
    .count {
      font-size: 13px;
    }
  }
</style>
