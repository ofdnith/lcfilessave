<script lang="ts">
  import Icon, { type IconName } from './Icon.svelte';
  import { duration } from '../lib/format';
  import type { Item } from '../lib/types';

  let { item, selected = false, selecting = false }: { item: Item; selected?: boolean; selecting?: boolean } = $props();

  const kindIcon: Record<Item['kind'], IconName> = {
    photo: 'photo',
    video: 'video',
    document: 'doc',
    audio: 'audio',
    other: 'file',
  };
  let failed = $state(false);
  const ext = $derived((item.original_name.split('.').pop() ?? '').slice(0, 5).toUpperCase());
</script>

<div class="thumb" class:selected class:selecting data-kind={item.kind}>
  {#if item.thumb_url && !failed}
    <img src={item.thumb_url} alt={item.original_name} loading="lazy" decoding="async" onerror={() => (failed = true)} />
  {:else}
    <div class="ph">
      <Icon name={kindIcon[item.kind]} size={26} />
      {#if item.kind !== 'photo' && item.kind !== 'video'}<span class="ext">{ext}</span>{/if}
    </div>
  {/if}

  {#if item.kind === 'video'}
    <span class="corner br"><Icon name="play" size={11} fill />{duration(item.duration_ms)}</span>
  {/if}
  {#if item.is_live_photo}
    <span class="corner tl live" title="Live Photo"><Icon name="live" size={13} /></span>
  {/if}
  {#if item.important}
    <span class="corner tr star" title="Importante"><Icon name="star" size={13} fill /></span>
  {/if}
  {#if item.volume && !item.on_server}
    <span class="volume" title="Original no {item.volume.name}">{item.volume.name}</span>
  {/if}
  {#if selecting}
    <span class="check" aria-hidden="true">{#if selected}<Icon name="check" size={14} />{/if}</span>
  {/if}
</div>

<style>
  .thumb {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    background: var(--raised);
    overflow: hidden;
    transition: transform 0.14s var(--ease), border-radius 0.14s;
  }
  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .ph {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 4px;
    color: var(--faint);
    background: linear-gradient(160deg, var(--raised), var(--surface));
  }
  .ext {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .corner {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
    filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.5));
  }
  .br {
    right: 6px;
    bottom: 5px;
  }
  .tl {
    left: 6px;
    top: 6px;
  }
  .tr {
    right: 6px;
    top: 6px;
  }
  .star {
    color: var(--accent);
  }
  /* The drive badge mimics the paper label stuck on an external drive. */
  .volume {
    position: absolute;
    left: 5px;
    bottom: 5px;
    padding: 1px 5px 1px 4px;
    border-radius: 3px;
    background: #f3e7c9;
    color: #3b2c0c;
    font-size: 9.5px;
    font-weight: 750;
    letter-spacing: 0.02em;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
    border-left: 3px solid var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .check {
    position: absolute;
    top: 6px;
    left: 6px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.85);
    background: rgba(0, 0, 0, 0.25);
    display: grid;
    place-items: center;
    color: var(--accent-ink);
  }
  .selected .check {
    background: var(--accent);
    border-color: var(--accent);
  }
  .selected {
    transform: scale(0.88);
    border-radius: 8px;
  }
  .selecting .live {
    display: none;
  }
</style>
