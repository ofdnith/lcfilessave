<script lang="ts">
  import type { Snippet } from 'svelte';

  let { label, onclose, children }: { label: string; onclose: () => void; children: Snippet } = $props();
  let panel = $state<HTMLElement | null>(null);

  $effect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panel?.focus();
    return () => prev?.focus?.();
  });

  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<div class="scrim" role="presentation" onclick={onclose}></div>
<div class="sheet" role="dialog" aria-modal="true" aria-label={label} tabindex="-1" bind:this={panel} onkeydown={key}>
  <div class="grip" aria-hidden="true"></div>
  {@render children()}
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 180;
    background: rgba(5, 8, 12, 0.6);
    animation: fade 0.15s;
  }
  .sheet {
    position: fixed;
    z-index: 181;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(440px, calc(100vw - 32px));
    max-height: min(640px, calc(100vh - 64px));
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    padding: 20px;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
    outline: none;
    animation: pop 0.16s var(--ease);
  }
  .grip {
    display: none;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: translate(-50%, -48%);
    }
  }
  @media (max-width: 899px) {
    .sheet {
      left: 0;
      right: 0;
      top: auto;
      bottom: 0;
      transform: none;
      width: 100%;
      max-height: 82vh;
      border-radius: 18px 18px 0 0;
      border-bottom: 0;
      padding: 10px 18px calc(var(--sab) + 18px);
      animation: slide 0.2s var(--ease);
    }
    .grip {
      display: block;
      width: 40px;
      height: 4px;
      border-radius: 2px;
      background: var(--line);
      margin: 0 auto 12px;
    }
    @keyframes slide {
      from {
        transform: translateY(40px);
        opacity: 0;
      }
    }
  }
</style>
