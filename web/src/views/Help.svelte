<script lang="ts">
  // Tutorials: #/ajuda (index) and #/ajuda/<slug> (one topic). The content lives
  // in lib/help.ts, shared by the web app, the iPhone app and the computer app.
  import Icon from '../components/Icon.svelte';
  import { helpGroups, helpTopics, type HelpTopic } from '../lib/help';
  import { isNative } from '../lib/native';
  import { href } from '../lib/router.svelte';

  let { slug }: { slug: string | null } = $props();

  const topic = $derived(slug ? helpTopics.find((t) => t.slug === slug) ?? null : null);
  let q = $state('');

  const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  function haystack(t: HelpTopic): string {
    return fold(
      [t.title, t.summary, ...t.sections.flatMap((s) => [s.heading, s.text ?? '', ...(s.steps ?? []), ...(s.tips ?? [])])].join(' '),
    );
  }
  const found = $derived(q.trim() ? helpTopics.filter((t) => fold(q).split(/\s+/).every((w) => haystack(t).includes(w))) : null);

  const whereLabel = { iphone: 'iPhone', mac: 'Computador', servidor: 'Servidor' } as const;
  // The topic most useful where the person is right now goes first.
  const here = isNative() ? 'mac' : 'iphone';

  function esc(s: string): string {
    return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
  }
  /** Only **bold** and [text](#/route) links; everything else is escaped. */
  function rich(s: string): string {
    return esc(s)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\((#\/[^)\s]*)\)/g, '<a href="$2">$1</a>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  const related = $derived(
    topic?.related?.map((s) => helpTopics.find((t) => t.slug === s)).filter((t): t is HelpTopic => !!t) ?? [],
  );
  const groupTopics = (key: string) =>
    helpTopics
      .filter((t) => t.group === key && t.slug !== 'primeiros-passos')
      .sort((a, b) => Number(b.where.includes(here)) - Number(a.where.includes(here)));
</script>

{#snippet card(t: HelpTopic)}
  <a class="topic" href={href('ajuda', t.slug)}>
    <span class="t-main">
      <strong>{t.title}</strong>
      <span class="muted">{t.summary}</span>
      <span class="where">{#each t.where as w}<span>{whereLabel[w]}</span>{/each}</span>
    </span>
    <Icon name="right" size={16} />
  </a>
{/snippet}

<div class="page help">
  {#if slug && topic}
    <a class="back" href={href('ajuda')}><Icon name="left" size={16} /> Ajuda</a>
    <h1 class="page-title">{topic.title}</h1>
    <p class="page-sub">{topic.summary}</p>
    <p class="where top">{#each topic.where as w}<span>{whereLabel[w]}</span>{/each}</p>

    {#each topic.sections as sec, i (i)}
      <section class="sec">
        <h2>{sec.heading}</h2>
        {#if sec.text}
          {#each sec.text.split('\n\n') as para}<p>{@html rich(para)}</p>{/each}
        {/if}
        {#if sec.steps?.length}
          <ol class="steps">
            {#each sec.steps as step}<li>{@html rich(step)}</li>{/each}
          </ol>
        {/if}
        {#if sec.tips?.length}
          <div class="tips">
            <Icon name="info" size={17} />
            <ul>{#each sec.tips as tip}<li>{@html rich(tip)}</li>{/each}</ul>
          </div>
        {/if}
      </section>
    {/each}

    {#if related.length}
      <h2 class="rel-title">Veja também</h2>
      <div class="list">{#each related as t (t.slug)}{@render card(t)}{/each}</div>
    {/if}
  {:else}
    <h1 class="page-title">Ajuda</h1>
    {#if slug}
      <p class="banner">Esse tutorial não existe mais. Procure abaixo.</p>
    {/if}
    <p class="page-sub">Tutoriais passo a passo de tudo o que o Acervo faz, no iPhone, no computador e no servidor.</p>
    <label class="search">
      <Icon name="search" size={18} />
      <input type="search" placeholder="Procurar na ajuda: backup, lote, Safari…" bind:value={q} />
    </label>

    {#if found}
      {#if found.length}
        <div class="list">{#each found as t (t.slug)}{@render card(t)}{/each}</div>
      {:else}
        <p class="muted">Nada encontrado para “{q}”.</p>
      {/if}
    {:else}
      <a class="start" href={href('ajuda', 'primeiros-passos')}>
        <Icon name="book" size={22} />
        <span><strong>Comece aqui: como o Acervo funciona</strong><span class="muted">O caminho de uma foto, do iPhone até o armazenamento, em 5 minutos.</span></span>
        <Icon name="right" size={16} />
      </a>
      {#each helpGroups as g (g.key)}
        {@const list = groupTopics(g.key)}
        {#if list.length}
          <h2 class="group">{g.label}</h2>
          <div class="list">{#each list as t (t.slug)}{@render card(t)}{/each}</div>
        {/if}
      {/each}
    {/if}
  {/if}
</div>

<style>
  .help {
    max-width: 760px;
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: var(--page-top, var(--sat));
    padding: 8px 0 4px;
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
  }
  .back + .page-title {
    padding-top: 0;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 44px;
    padding: 0 14px;
    margin-bottom: 18px;
    border-radius: 999px;
    background: var(--raised);
    color: var(--muted);
  }
  .search input {
    flex: 1;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    font-size: 16px;
    color: var(--text);
  }
  .start {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 16px;
    margin-bottom: 8px;
    border-radius: var(--r-lg);
    background: var(--accent-soft);
    border: 1px solid rgba(240, 180, 76, 0.3);
    color: var(--accent);
    text-decoration: none;
  }
  .start > span {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .start strong {
    color: var(--text);
  }
  .start .muted {
    font-size: 13.5px;
  }
  .group,
  .rel-title {
    font-size: 14px;
    color: var(--muted);
    font-weight: 600;
    margin: 22px 0 8px;
  }
  .list {
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--line-soft);
    border-radius: var(--r-lg);
    overflow: hidden;
  }
  .topic {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 13px 16px;
    color: var(--text);
    text-decoration: none;
  }
  .topic + .topic {
    border-top: 1px solid var(--line-soft);
  }
  .topic:hover {
    background: var(--raised);
  }
  .topic > :global(svg) {
    flex: none;
    color: var(--faint);
  }
  .t-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .t-main .muted {
    font-size: 13.5px;
  }
  .where {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
  }
  .where span {
    font-size: 11px;
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 999px;
    background: var(--raised-2);
    color: var(--muted);
  }
  .where.top {
    margin: -10px 0 8px;
  }
  .sec {
    margin-top: 22px;
  }
  .sec h2 {
    font-size: 18px;
    margin-bottom: 8px;
  }
  .sec p {
    margin: 0 0 10px;
    line-height: 1.55;
  }
  .steps {
    margin: 0 0 12px;
    padding: 0;
    list-style: none;
    counter-reset: step;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .steps li {
    position: relative;
    counter-increment: step;
    padding-left: 38px;
    line-height: 1.55;
    min-height: 26px;
  }
  .steps li::before {
    content: counter(step);
    position: absolute;
    left: 0;
    top: 0;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 700;
    font-size: 13px;
    display: grid;
    place-items: center;
  }
  .tips {
    display: flex;
    gap: 10px;
    padding: 12px 14px;
    border-radius: var(--r-md);
    background: rgba(143, 185, 255, 0.08);
    color: var(--info);
  }
  .tips :global(svg) {
    flex: none;
    margin-top: 2px;
  }
  .tips ul {
    margin: 0;
    padding-left: 16px;
    color: var(--text);
    font-size: 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .help :global(code) {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.9em;
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--raised-2);
  }
  .help :global(strong) {
    font-weight: 650;
  }
  @media (max-width: 899px) {
    .sec h2 {
      font-size: 17px;
    }
  }
</style>
