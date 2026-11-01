<script lang="ts">
  // Small "how does this work?" link to a tutorial in the help center.
  import Icon from './Icon.svelte';
  import { href } from '../lib/router.svelte';

  let { slug, label = 'Como funciona' }: { slug: string; label?: string } = $props();
</script>

<a class="help-link" href={href('ajuda', slug)}><Icon name="help" size={15} /> {label}</a>

<style>
  .help-link {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 13px;
    color: var(--info);
    text-decoration: none;
    white-space: nowrap;
  }
  .help-link:hover {
    text-decoration: underline;
  }
</style>
