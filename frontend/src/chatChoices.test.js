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


const indonesianRoleplay = `A) Kamu membuka pintu kamar Mr. Jenkins
B) Kamu mencari informasi lebih lanjut tentang suara aneh
C) Kamu kembali ke luar villa untuk mencari bantuan
D) Kamu mencari tempat untuk duduk dan menunggu`;
const englishRoleplay = `A) You open Mr. Jenkins' bedroom door
B) You investigate the strange noise
C) You return outside the villa for help
D) You find somewhere to sit and wait`;

test('representative Indonesian roleplay preserves all four descriptions', () => {
  const response = indonesianRoleplay + '\n\nPilihlah tindakan yang kamu inginkan.';
  assert.deepEqual(parseChoices(response)?.options, [
    { label: 'A', text: 'Kamu membuka pintu kamar Mr. Jenkins' },
    { label: 'B', text: 'Kamu mencari informasi lebih lanjut tentang suara aneh' },
    { label: 'C', text: 'Kamu kembali ke luar villa untuk mencari bantuan' },
    { label: 'D', text: 'Kamu mencari tempat untuk duduk dan menunggu' },
  ]);
});

for (const [options, prompts] of [
  [indonesianRoleplay, [
    'Pilihlah tindakan yang kamu inginkan.',
    'Pilihlah salah satu tindakan',
    'Apa yang akan kamu lakukan selanjutnya?',
    'Kamu mau pilih yang mana?',
  ]],
  [englishRoleplay, [
    'Choose the action you want.',
    'Select one action.',
    'What will you do next?',
    'What would you like to do next?',
    'Which option would you choose?',
    'Which would you pick?',
  ]],
]) for (const prompt of prompts) {
  for (const position of ['before', 'after']) test(`pronoun options with nearby prompt: ${position} ${prompt}`, () => {
    const text = position === 'before' ? prompt + '\n\n' + options : options + '\n\n' + prompt;
    const group = parseChoices(text);
    assert.equal(group?.options.length, 4);
    assert.equal(group.options[0].text, options.split('\n')[0].slice(3));
  });
}

for (const [name, text] of [
  ['Indonesian pronouns without a decision cue', indonesianRoleplay],
  ['English pronouns without a decision cue', englishRoleplay],
  ['ordinary instructions', 'Instructions:\n' + englishRoleplay + '\nWhat would you like to do next?'],
  ['Indonesian procedural guide', 'Ikuti langkah-langkah ini:\n' + indonesianRoleplay + '\nPilihlah salah satu tindakan'],
  ['documentation with a new prompt', 'Documentation:\n' + englishRoleplay + '\nWhich option would you choose?'],
  ['code with a new prompt', '```text\n' + indonesianRoleplay + '\nPilihlah salah satu tindakan\n```'],
  ['quoted decision', (indonesianRoleplay + '\nPilihlah tindakan yang kamu inginkan.').split('\n').map(line => '> ' + line).join('\n')],
  ['technical list with a new prompt', '1. Install dependencies\n2. Run tests\n3. Deploy\nPilihlah salah satu tindakan'],
  ['example with a new prompt', 'Contoh:\n' + indonesianRoleplay + '\nPilihlah salah satu tindakan'],
  ['distant decision cue', 'Pilihlah salah satu tindakan.\n' + 'The room is quiet. '.repeat(30) + '\n' + indonesianRoleplay],
]) test('reject expanded-cue false positive: ' + name, () => assert.equal(parseChoices(text), null));
