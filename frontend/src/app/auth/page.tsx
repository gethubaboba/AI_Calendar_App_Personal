'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { apiLogin, apiRegister, apiMfaVerify, tokens } from '@/lib/api';

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [challenge, setChallenge] = useState('');
  const [code, setCode] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!challenge && (!email || !password)) { setError('Заполните все поля'); return; }
    if (!challenge && mode === 'register' && !name) { setError('Введите имя'); return; }

    setLoading(true);
    try {
      const result = challenge ? await apiMfaVerify(challenge, code.trim()) : mode === 'login'
        ? await apiLogin(email, password)
        : await apiRegister(email, name, password);

      if ('mfa_required' in result) {
        tokens.clear();
        setPassword('');
        setChallenge(result.challenge_token);
        return;
      }
      tokens.set(result.access_token, result.refresh_token);
      router.push('/dashboard');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Ошибка входа');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center mb-8">
          <div className="h-16 w-16 rounded-2xl bg-emerald-500 flex items-center justify-center mb-4 shadow-lg">
            <span className="text-white text-2xl font-bold">УК</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-800">Умный Календарь</h1>
          <p className="text-slate-500 text-sm mt-1">Управляй своим временем эффективно</p>
        </div>

        <div className="bg-white rounded-2xl shadow-sm p-8">
          {!challenge && <div className="flex rounded-xl bg-slate-100 p-1 mb-6">
            <button
              onClick={() => { setMode('login'); setError(''); }}
              className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${
                mode === 'login' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Войти
            </button>
            <button
              onClick={() => { setMode('register'); setError(''); }}
              className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${
                mode === 'register' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Регистрация
            </button>
          </div>}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {challenge ? <>
              <h2 className="font-semibold text-slate-800">Подтверждение входа</h2>
              <label htmlFor="mfa-code" className="text-sm text-slate-600">Введите код из приложения-аутентификатора или один резервный код.</label>
              <input id="mfa-code" autoFocus autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} maxLength={64} required className="w-full px-4 py-2.5 border border-slate-200 rounded-xl" />
              <button type="button" disabled={loading} onClick={() => { setChallenge(''); setCode(''); setError(''); }} className="text-sm text-emerald-700">Вернуться ко входу</button>
            </> : <>
            {mode === 'register' && (
              <div>
                <label htmlFor="auth-name" className="block text-sm font-medium text-slate-700 mb-1">Имя</label>
                <input
                  id="auth-name"
                  autoComplete="name"
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Николай Шибитов"
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:border-transparent"
                />
              </div>
            )}
            <div>
              <label htmlFor="auth-email" className="block text-sm font-medium text-slate-700 mb-1">Email</label>
              <input
                id="auth-email"
                autoComplete="username"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:border-transparent"
              />
            </div>
            <div>
              <label htmlFor="auth-password" className="block text-sm font-medium text-slate-700 mb-1">Пароль</label>
              <input
                id="auth-password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:border-transparent"
              />
            </div>

            </>}
            {error && (
              <p role="alert" className="text-red-500 text-sm bg-red-50 px-3 py-2 rounded-lg">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-60 text-white font-medium rounded-xl text-sm transition-colors mt-1"
            >
              {loading ? 'Загрузка...' : challenge ? 'Подтвердить вход' : mode === 'login' ? 'Войти' : 'Создать аккаунт'}
            </button>
          </form>
          {!challenge && mode === 'login' && <Link href="/forgot-password" className="block text-center mt-4 text-sm text-emerald-700 hover:underline">Забыли пароль?</Link>}

        </div>
      </div>
    </div>
  );
}
