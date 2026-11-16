import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseChoices, choicePrompt, eligibleChoices } from './chatChoices.js';

const alpha = 'A) Open the door\nB) Investigate the noise\nC) Call for help\nD) Wait';
for (const [name, text, count] of [
  ['alphabetic', alpha, 4],
  ['periods', 'A. Open the door\nB. Wait\nC. Call for help', 3],
  ['numeric', 'Choose your action:\n1. Open the door\n2. Wait\n3. Call\n4. Hide', 4],
  ['Markdown', '**A)** Membuka pintu\n**B)** Menunggu\nApa pilihanmu?', 2],
  ['bulleted markers', '- **A.** Open the door\n- **B.** Wait\nChoose your action.', 2],
  ['bullets', 'Pilih satu opsi:\n- Membuka pintu\n- Menunggu', 2],
  ['eight', Array.from({length:8}, (_, i) => `${String.fromCharCode(65+i)}) Open route ${i}`).join('\n'), 8],
  ['story', 'The scene is silent. Choose your action.\n' + alpha, 4],
  ['wrapped', 'A) Open the door\n  without making noise\nB) Wait', 2],
]) test(name, () => assert.equal(parseChoices(text)?.options.length, count));

for (const [name, text] of [
  ['Python', '```python\n' + alpha + '\n```'],
  ['JavaScript', '```js\n' + alpha + '\n```'],
  ['JSON', '{\n"choices": []\n}\n' + alpha],
  ['YAML', 'Configuration example:\n' + alpha],
  ['installation', '1. Install dependencies\n2. Run tests\n3. Deploy'],
  ['tutorial', 'Choose your action in this tutorial:\n' + alpha],
  ['math', '1. x = 2\n2. y = 3'],
  ['citations', 'References:\n' + alpha],
  ['table', '| A | B |\n' + alpha],
  ['quoted', '> Choose your action\n> A) Open\n> B) Wait'],
  ['single', 'A) Open'],
  ['inconsistent', 'A) Open\nC) Wait'],
  ['style', 'A) Open\nB. Wait'],
  ['nine', alpha + '\nE) Hide\nF) Run\nG) Shout\nH) Listen\nI) Sleep'],
  ['missing text', 'A)\nB) Wait'],
  ['bare ambiguous headings', 'A. Background\nB. Methods'],
  ['explicit quoted example', 'Example: Choose your action\n' + alpha],
  ['documentation', 'The available parameters are:\n' + alpha],
  ['unrelated closing', alpha + '\nThe weather is cold.'],
  ['unindented wrap', 'A) Open\nunrelated prose\nB) Wait'],
]) test('reject ' + name, () => assert.equal(parseChoices(text), null));

test('only latest persisted completed assistant qualifies', () => {
  const m = {id: 2, role:'assistant', content:alpha};
  assert.ok(eligibleChoices(m, m));
  for (const item of [{...m, incomplete:true}, {...m, id:undefined}, {...m, role:'user'}]) assert.equal(eligibleChoices(item, item), null);
  assert.equal(eligibleChoices(m, {...m, id:4}), null);
});
test('prompts preserve descriptions, ordering and decision context', () => {
  const group = parseChoices(alpha);
  assert.equal(choicePrompt(group, ['B', 'A']), 'Saya memilih opsi B: Investigate the noise; lalu opsi A: Open the door. Lanjutkan berdasarkan gabungan kedua pilihan ini secara masuk akal.');
  assert.equal(choicePrompt(group, ['D']), 'Saya memilih opsi D: Wait. Lanjutkan berdasarkan pilihan ini.');
  assert.match(choicePrompt(parseChoices('Choose your action in this story:\n' + alpha), ['A']), /Lanjutkan cerita/);
  for (const selection of [[], ['A','B','C'], ['A','A'], ['Z']]) assert.throws(() => choicePrompt(group, selection));
});
test('untrusted descriptions remain text', () => {
  const group = parseChoices('Choose your action:\nA) <img src=x onerror=alert(1)>\nB) [Go](https://evil.example)');
  assert.equal(group.options[0].text, '<img src=x onerror=alert(1)>');
  assert.ok(choicePrompt(group, ['A']).includes(group.options[0].text));
});
