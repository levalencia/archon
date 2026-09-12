import { expect, test, type Page, type Route } from '@playwright/test';

const base = {
  status: 'published', language: 'en', media_type: 'application/json',
  sha256: 'b'.repeat(64), source_commit: 'a'.repeat(40),
  limitations: ['Derived learning material, not canonical evidence.'],
};
const artifacts = [
  { ...base, id: 'request-deck', type: 'deck', title: 'Request Lifecycle Visual Deck' },
  { ...base, id: 'request-diagram-1', type: 'diagram', title: 'Governed Request Path' },
  { ...base, id: 'request-diagram-3', type: 'infographic', title: 'Evidence Ladder' },
  { ...base, id: 'request-audio', type: 'audio', title: 'Request Lifecycle Audio Lesson', media_type: 'audio/mpeg' },
  { ...base, id: 'request-mind-map', type: 'mind-map', title: 'Request Lifecycle Mind Map' },
  { ...base, id: 'request-flashcards', type: 'flashcards', title: 'Request Lifecycle Flashcards' },
  { ...base, id: 'request-quiz', type: 'quiz', title: 'Request Lifecycle Scenario Quiz' },
  { ...base, id: 'request-study-guide', type: 'study-guide', title: 'Request Lifecycle Study Guide' },
];
const systemDeck = { ...base, id: 'system-overview-deck', type: 'deck', title: 'Cogentrex — System Overview — Presentation' };
const codeFirstVideo = { ...base, id: 'code-first-video-02', type: 'video', title: 'Video 2 — Building the FastAPI Application', status: 'review-ready', media_type: 'video/mp4', duration_seconds: 679.766667 };
const catalog = { schema: 'cogentrex.learning-library', version: 1, generated_at: '2026-09-04T12:00:00Z', source_commit: 'a'.repeat(40), packs: [
  { id: 'request-lifecycle', title: 'Cogentrex Request Lifecycle', purpose: 'Follow one request.', artifacts },
  { id: 'system-overview', title: 'Cogentrex — System Overview', purpose: 'Understand the system.', artifacts: [systemDeck] },
  { id: 'code-first-series', title: 'Cogentrex From the Code', purpose: 'Learn from source-grounded videos.', artifacts: [codeFirstVideo] },
] };
const nodeTeaching = {
  definition: 'The runtime is the bounded interpreter around the probabilistic model.',
  receives: ['Authenticated request', 'Resolved context'],
  responsibility: 'Advance typed run states and enforce limits.',
  produces: ['Runtime events', 'Explicit stop reason'],
  controls: ['Tool-call budget', 'Deadline'],
  failure_behavior: 'A failed limit stops the run explicitly.',
  why_it_matters: 'The model proposes, while deterministic runtime code controls execution.',
};
const edgeTeaching = {
  payload: 'An authenticated request crosses the application boundary.',
  transformation: 'Client state becomes a typed API request.',
  trust_boundary: 'The request leaves the browser and enters Cogentrex.',
  precondition: 'The client has a request to submit.',
  failure_behavior: 'A network failure stops before runtime execution.',
  why_it_matters: 'Transport does not grant execution authority.',
};
const details: Record<string, Record<string, unknown>> = {
  'request-deck': { ...artifacts[0], content: { slides: [{ id: 's1', title: 'One Request, Many Trust Boundaries', message: 'The model proposes; deterministic systems execute.', visual: 'governed request path', notes: 'Explain the trust boundary.', presenter_script: 'Explain the request as a sequence of governed transitions for a newcomer, then distinguish model intent from deterministic execution evidence.', key_terms: [{term:'Trust boundary',definition:'Where responsibility changes.'}], common_misconception:'The model executes tools directly.', transition:'Next: policy.', sources: ['docs/ARCHITECTURE-DIAGRAMS.md'] }, { id: 's2', title: 'Policy Is Deterministic', message: 'ALLOW, ASK, or DENY.', visual: 'policy gate', notes: 'The model cannot self-authorize.', sources: ['docs/course/modules/05-policy-and-approvals/README.md'] }] } },
  'request-diagram-1': { ...artifacts[1], content: { title: 'Governed Request Path', description: 'A labeled request flow.', sources:['docs/ARCHITECTURE-DIAGRAMS.md'], nodes: [{ id: 'browser', label: 'Browser', kind: 'frontend', summary:'Starts the request.',details:'Starts the request.',teaching:nodeTeaching,sources:['docs/ARCHITECTURE-DIAGRAMS.md'] }, { id: 'runtime', label: 'Runtime', kind: 'backend',summary:'Owns bounded execution.',details:'Owns bounded execution.',teaching:nodeTeaching,sources:['docs/course/modules/02-typed-runtime/README.md'] }], edges: [{ id:'browser-runtime',source: 'browser', target: 'runtime', label: 'HTTP request',explanation:'The request crosses the application boundary.',teaching:edgeTeaching,sources:['docs/ARCHITECTURE-DIAGRAMS.md'] }] } },
  'request-diagram-3': { ...artifacts[2], content: { title:'Evidence Ladder',description:'Claims grow only when evidence grows.',sources:['docs/IMPLEMENTATION-EVIDENCE.md'],nodes:[{id:'source',label:'Source exists',kind:'backend',summary:'Implementation exists.',details:'Implementation exists.',teaching:nodeTeaching},{id:'tests',label:'Deterministic tests',kind:'backend',summary:'Behavior repeats.',details:'Behavior repeats.',teaching:nodeTeaching},{id:'local',label:'Local runtime',kind:'database',summary:'Stack observed.',details:'Stack observed.',teaching:nodeTeaching},{id:'live',label:'Live provider',kind:'external',summary:'Provider observed.',details:'Provider observed.',teaching:nodeTeaching},{id:'public',label:'Public deployment',kind:'external',summary:'Deployment observed.',details:'Deployment observed.',teaching:nodeTeaching}],edges:[],modules:[{id:'evidence-before-confidence',label:'Evidence before confidence',category:'principle',summary:'Start with observation.',details:'A claim is only as strong as the evidence actually collected.',sources:['docs/IMPLEMENTATION-EVIDENCE.md']},{id:'capability-claim',label:'Capability claim',category:'architecture',summary:'The statement under review.',details:'A claim names behavior and evidence boundary.',sources:['docs/IMPLEMENTATION-EVIDENCE.md']},{id:'code-proof',label:'Code',category:'architecture',summary:'Implementation exists.',details:'Code proves implementation, not runtime behavior.',sources:['docs/IMPLEMENTATION-EVIDENCE.md']}] } },
  'request-audio': { ...artifacts[3], content: { segments: [{ chapter: 'The mental model', speaker: 'narrator', text: 'Cogentrex is a bounded interpreter around a probabilistic model.',sources:['docs/ARCHITECTURE-DIAGRAMS.md'] }] } },
  'request-mind-map': { ...artifacts[4], content: { root: { id: 'root', label: 'Cogentrex Request Lifecycle', summary: 'A governed path.', sources: ['docs/ARCHITECTURE-DIAGRAMS.md'], children: [{ id: 'runtime', label: 'Bounded runtime', summary: 'Explicit budgets and state.', sources: ['docs/course/modules/02-typed-runtime/README.md'], children: [{id:'budget',label:'Budgets',summary:'Bound cost and time.',sources:['docs/course/modules/02-typed-runtime/README.md'],children:[]}] }] } } },
  'request-flashcards': { ...artifacts[5], content: { cards: [{ id: 'c1', question: 'Who executes a tool?', answer: 'The runtime.', explanation: 'The model proposes intent.', misconception: 'The model executes code directly.', sources: ['docs/course/modules/04-tools-and-schemas/README.md'] }] } },
  'request-quiz': { ...artifacts[6], content: { questions: [{ id: 'q1', scenario: 'Policy returns ASK.', options: ['Execute now', 'Wait for approval'], correct_index: 1, explanation: 'ASK requires approval.', sources: ['docs/course/modules/05-policy-and-approvals/README.md'] }] } },
  'request-study-guide': { ...artifacts[7], content: { sections: [{ heading: 'Mental model', body: 'The runtime is a bounded interpreter.', sources: ['docs/course/modules/02-typed-runtime/README.md'] }] } },
  'code-first-video-02': { ...codeFirstVideo, content: { segments: [{ chapter: 'Factory pattern', speaker: 'narrator', start_seconds: 206.692, end_seconds: 259.3, text: 'Create app centralizes construction and supports controlled injection.', sources: [{ path: 'backend/app/main.py', line_start: 391, line_end: 401 }] }] } },
};

async function mockLibrary(page: Page) {
  await page.addInitScript(() => localStorage.setItem('cogentrex_token', 'playwright-token'));
  await page.route('**/api/learning-tutor/answer', async (route: Route) => {
    return route.fulfill({ json: {
      run_id: 'run-tutor-1', session_id: 'session-tutor-1',
      answer_markdown: '## Direct answer\nA service slot reserves an application-owned location. [E1]\n\n## Code excerpts\n```python\napp.state.sandbox_executor = None\n```',
      citations: [{ ...base, id: 'E1', kind: 'code', title: 'main.py — create_app', excerpt: 'app.state.sandbox_executor = None', score: 1, source_commit: 'a'.repeat(40), locator: { path: 'backend/app/main.py', line_start: 418, line_end: 420 } }],
      related_questions: ['When does lifespan populate the slot?'], diagram: null,
      grounded: true, unsupported: [], metrics: { faithfulness_score: 1 },
    } });
  });
  await page.route('**/api/learning-media/**', async (route: Route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/catalog')) return route.fulfill({ json: catalog });
    if (url.pathname.endsWith('/access')) return route.fulfill({ json: { url: '/api/learning-media/media/test', expires_at: 9999999999 } });
    const id = url.pathname.split('/').at(-1) ?? '';
    if (id === 'system-overview-deck') {
      return route.fulfill({ json: { ...details['request-deck'], ...systemDeck } });
    }
    return route.fulfill({ json: details[id] ?? {}, status: details[id] ? 200 : 404 });
  });
}

test('published Present artifacts open as an interactive English deck and diagram', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=present');
  await expect(page.getByRole('heading', { name: 'One Request, Many Trust Boundaries' })).toBeVisible();
  await page.getByRole('button', { name: 'Teach this slide' }).click();
  await expect(page.getByText('Presenter script')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Architecture Diagrams' })).toHaveAttribute('href', /github\.com\/levalencia\/cogentrex\/blob\/a{40}/);
  await page.getByRole('button', { name: 'Next slide' }).click();
  await expect(page.getByRole('heading', { name: 'Policy Is Deterministic' })).toBeVisible();
  await page.getByRole('button', { name: /Governed Request Path/ }).click();
  await expect(page.getByText('HTTP request', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Read 1 through 2')).toBeVisible();
  await page.getByRole('button', { name: 'Step 2: Runtime' }).click();
  await expect(page.getByRole('heading', { name: 'Controls and guarantees' })).toBeVisible();
  await page.getByRole('button', { name: 'HTTP request: browser to runtime' }).click();
  await expect(page.getByRole('heading', { name: 'What crosses this boundary' })).toBeVisible();
  await page.locator('details.steps summary').click();
  await page.locator('details.steps button').first().click();
  await expect(page.getByText('The request crosses the application boundary.').first()).toBeVisible();
  await page.getByRole('button', { name: /Evidence Ladder/ }).click();
  await expect(page.getByRole('heading', { name: 'Evidence architecture' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'How confidence grows' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Claim review checklist' })).toBeVisible();
  await page.getByRole('button', { name: /Evidence before confidence/ }).click();
  await expect(page.getByText('A claim is only as strong as the evidence actually collected.')).toBeVisible();
});

test('published Study artifacts support mind map, flashcard, quiz, and guide interactions', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=study');
  await expect(page.getByText('Cogentrex Request Lifecycle', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Bounded runtime' }).click();
  await expect(page.getByText('Budgets', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: /Request Lifecycle Flashcards/ }).click();
  await page.getByRole('button', { name: 'Reveal answer' }).click();
  await expect(page.getByText('The runtime.', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /Tools And Schemas/i })).toHaveAttribute('href', /github\.com/);
  await page.getByRole('button', { name: /Request Lifecycle Scenario Quiz/ }).click();
  await page.getByText('Wait for approval', { exact: true }).click();
  await page.getByRole('button', { name: 'Check answer' }).click();
  await expect(page.getByRole('alert')).toContainText('Correct');
  await page.getByRole('button', { name: /Request Lifecycle Study Guide/ }).click();
  await expect(page.getByRole('heading', { name: 'Mental model' })).toBeVisible();
});

test('learner can switch between published learning packs', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=present');
  await page.getByRole('button', { name: 'Cogentrex — System Overview', exact: true }).click();
  await expect(page.getByRole('button', { name: /Cogentrex — System Overview — Presentation/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Cogentrex — System Overview — Presentation' })).toBeVisible();
});

test('Present view opens a code-first video with timed transcript and source link', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=present');
  await page.getByRole('button', { name: 'Cogentrex From the Code', exact: true }).click();
  await expect(page.getByRole('button', { name: /Video 2 — Building the FastAPI Application/ })).toBeVisible();
  await expect(page.getByLabel('Video lesson player')).toBeVisible();
  await page.getByText('Accessible transcript').click();
  await expect(page.getByRole('heading', { name: 'Factory pattern' })).toBeVisible();
  await expect(page.getByText('Create app centralizes construction and supports controlled injection.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Main' })).toHaveAttribute('href', /main\.py#L391-L401/);
});

test('every learning page exposes a tutor and Video 2 sends its timestamp', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=present&pack=code-first-series&artifact=code-first-video-02&t=300');
  await page.getByRole('button', { name: 'Ask about this topic' }).click();
  await expect(page.getByRole('complementary', { name: 'Learning tutor' })).toContainText('Video 2');
  await page.getByLabel('Question about this topic').fill('What is a service slot?');
  const requestPromise = page.waitForRequest('**/api/learning-tutor/answer');
  await page.getByRole('button', { name: 'Ask Cogentrex tutor' }).click();
  const request = await requestPromise;
  expect(request.postDataJSON().context).toMatchObject({
    view: 'present', artifact_id: 'code-first-video-02', playback_seconds: 300,
  });
  await expect(page.getByText('A service slot reserves an application-owned location. [E1]')).toBeVisible();
  await expect(page.getByText('app.state.sandbox_executor = None').first()).toBeVisible();
});

test('published Listen view exposes English audio and transcript', async ({ page }) => {
  await mockLibrary(page);
  await page.goto('/learn?view=listen');
  await expect(page.getByRole('heading', { name: 'Review Cogentrex through English audio' })).toBeVisible();
  await expect(page.getByLabel('Audio lesson player')).toContainText('The mental model');
  await expect(page.getByText('English audio lesson')).toBeVisible();
});
