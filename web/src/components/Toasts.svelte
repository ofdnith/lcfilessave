<script lang="ts">
  import { app, dismissToast } from '../lib/state.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each app.toasts as t (t.id)}
    <div class="toast {t.tone}">
      <span>{t.text}</span>
      {#if t.action}
        <button
          onclick={() => {
            t.action?.run();
            dismissToast(t.id);
          }}>{t.action.label}</button
        >
      {/if}
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    z-index: 200;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(var(--sab) + 24px);
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: center;
    pointer-events: none;
    width: max-content;
    max-width: calc(100vw - 24px);
  }
  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 12px 10px 16px;
    border-radius: 12px;
    background: #2e3a47;
    color: var(--text);
    font-size: 14px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    animation: in 0.18s var(--ease);
  }
  .toast.error {
    background: #4a2826;
    color: #ffd9d5;
  }
  @keyframes in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  button {
    color: var(--accent);
    font-weight: 700;
    padding: 4px 6px;
    border-radius: 6px;
  }
  button:hover {
    background: rgba(255, 255, 255, 0.06);
  }
  @media (min-width: 900px) {
    .toasts {
      left: calc(50% + var(--sidebar) / 2);
    }
  }
  @media (max-width: 899px) {
    .toasts {
      bottom: calc(var(--sab) + var(--tabbar) + 76px);
    }
  }
</style>
