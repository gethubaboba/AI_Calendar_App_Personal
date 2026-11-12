'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Header from '@/components/Header';
import { AgentProposal, apiAgentChat, apiGetMe, confirmAgentProposal, previewSchedule, tokens } from '@/lib/api';

export default function AgentPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const [reply, setReply] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'advice' | 'propose'>('advice');
  const [proposal, setProposal] = useState<AgentProposal | null>(null);
  const [rowErrors, setRowErrors] = useState<{ row: number; error: string }[]>([]);

  function resetPreview() {
    setProposal(null);
    setRowErrors([]);
    setError('');
    setReply('');
  }

  async function upload(file?: File) {
    if (!file) return;
    resetPreview();
    if (file.size > 512 * 1024) { setError('Файл больше 512 КиБ'); return; }
    setLoading(true);
    try {
      const result = await previewSchedule(file);
      setProposal(result.proposal);
      setRowErrors(result.errors);
      if (!result.proposal) setReply('Нет строк для импорта.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Ошибка чтения файла'); }
    finally { setLoading(false); }
  }

  async function apply() {
    if (!proposal) return;
    setLoading(true);
    setError('');
    try {
      const result = await confirmAgentProposal(proposal.id);
      setReply(`Изменений сохранено: ${result.applied}`);
      setProposal(null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Ошибка подтверждения'); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    if (!tokens.getAccess()) { router.push('/auth'); return; }
    apiGetMe().then(user => setName(user.name)).catch(() => router.push('/auth'));
  }, [router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!message.trim()) return;
    setLoading(true);
    resetPreview();
    try {
      const result = await apiAgentChat(message.trim(), mode);
      setReply(result.reply);
      setProposal(result.proposal ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить ответ');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header userName={name} onCreateEvent={() => router.push('/dashboard')}
        onLogout={() => { tokens.clear(); router.push('/auth'); }} />
      <main className="mx-auto max-w-2xl p-4 sm:p-6">
        <h1 className="text-xl font-semibold">Ассистент календаря</h1>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <label className="block">Режим <select disabled={loading} value={mode}
            onChange={e => { setMode(e.target.value === 'advice' ? 'advice' : 'propose'); resetPreview(); }}>
            <option value="advice">Совет по календарю</option><option value="propose">Предложить изменение</option>
          </select></label>
          <label htmlFor="agent-question" className="block text-sm font-medium">Вопрос</label>
          <textarea id="agent-question" value={message} onChange={event => setMessage(event.target.value)}
            maxLength={2000} rows={4} className="w-full rounded-xl border p-3" />
          <button disabled={loading || !message.trim()} className="rounded-xl bg-emerald-600 px-4 py-3 text-white disabled:opacity-50">
            {loading ? 'Ожидание ответа…' : 'Отправить'}
          </button>
        </form>
        <section className="mt-6 rounded-xl bg-white p-4">
          <label className="block font-medium" htmlFor="schedule">Импорт расписания XLSX</label>
          <p className="my-2 text-sm">Один лист до 100 строк. Столбцы title и date обязательны. Для времени укажите start_time и end_time.</p>
          <input type="file" id="schedule" accept=".xlsx" disabled={loading} onChange={e => {
            const file = e.target.files?.[0]; e.target.value = ''; void upload(file);
          }} />
        </section>
        {rowErrors.map(e => <p key={e.row} className="text-red-700">Строка {e.row}: {e.error}</p>)}
        {proposal && <section className="mt-4 rounded-xl border p-4">
          <h2 className="font-semibold">Предпросмотр</h2>
          {proposal.changes.map((c, i) => <article key={i} className="border-b py-2">
            <strong>{{create:'Создать',update:'Изменить',delete:'Удалить'}[c.action]} {c.kind === 'note' ? 'заметку' : 'событие'} {c.entry_id}</strong>
            {[['Было', c.before], ['Станет', c.after]].map(([label, fields]) => fields && typeof fields === 'object' &&
              <div key={String(label)} className="break-words"><b>{String(label)}</b> {Object.entries(fields).filter(([,v]) => v != null).map(([k,v]) => `${k}: ${v}`).join(' · ')}</div>)}
          </article>)}
          <button disabled={loading} onClick={apply} className="mr-4 mt-3 rounded-lg bg-emerald-700 px-3 py-2 text-white">Подтвердить ({proposal.changes.length})</button>
          <button disabled={loading} onClick={resetPreview}>Отмена</button>
        </section>}
        {error && <p role="alert" className="mt-4 text-red-700">{error}</p>}
        {reply && <div className="mt-4 whitespace-pre-wrap rounded-xl bg-white p-4">{reply}</div>}
      </main>
    </div>
  );
}
