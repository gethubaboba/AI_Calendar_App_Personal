'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/auth');
  }, [router]);

  return <main><p>Открываем страницу входа… <Link href="/auth">Перейти ко входу</Link></p></main>;
}
