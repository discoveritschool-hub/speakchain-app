/* ════════════════════════════════════════════════════════════
   TOAST + REWARDS SYSTEM
   
   Підключи цей файл в кожен miniapp (Progress, Speaking Buddy):
   <script src="/toast_rewards.js"></script>
   
   Використання:
   showReward('buddy_session');                    // toast з рандомною фразою
   showReward('topic_used_correctly', {topic: 'Past Simple'});
   showReward('topic_levelup', {topic: 'Past Simple'});
   ════════════════════════════════════════════════════════════ */

(function() {
  'use strict';

  // ─── Інжектимо стилі ───
  if (!document.getElementById('toast-rewards-styles')) {
    const style = document.createElement('style');
    style.id = 'toast-rewards-styles';
    style.textContent = `
      .sc-toast-container {
        position: fixed; top: 12px; left: 12px; right: 12px;
        z-index: 9999; pointer-events: none;
        display: flex; flex-direction: column; gap: 8px;
      }
      .sc-toast {
        background: linear-gradient(135deg, #1e2a47 0%, #2a1a3a 100%);
        border: 1px solid rgba(124, 110, 247, 0.3);
        border-radius: 14px;
        padding: 12px 14px;
        display: flex; align-items: center; gap: 12px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        pointer-events: auto;
        animation: scToastIn 0.3s ease-out;
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
      }
      .sc-toast.removing { animation: scToastOut 0.25s ease-in forwards; }
      .sc-toast.success {
        background: linear-gradient(135deg, #0f3624 0%, #1e4733 100%);
        border-color: rgba(90,216,166,0.4);
      }
      .sc-toast.warning {
        background: linear-gradient(135deg, #2a1410 0%, #2a1a1a 100%);
        border-color: rgba(247,163,92,0.25);
      }
      .sc-toast.special {
        background: linear-gradient(135deg, #3a2410 0%, #4a1a2a 100%);
        border-color: rgba(247,163,92,0.4);
      }
      .sc-toast-icon { font-size: 28px; flex-shrink: 0; }
      .sc-toast-body { flex: 1; min-width: 0; }
      .sc-toast-rewards {
        display: flex; gap: 10px;
        font-size: 12px; font-weight: 600;
        margin-bottom: 3px;
      }
      .sc-toast-chain { color: #f7a35c; }
      .sc-toast-xp { color: #7c6ef7; }
      .sc-toast.success .sc-toast-xp { color: #5ad8a6; }
      .sc-toast.special .sc-toast-xp { color: #f7a35c; }
      .sc-toast-phrase {
        font-size: 13px; color: #eaeaf5;
        line-height: 1.35; font-weight: 500;
      }
      @keyframes scToastIn {
        from { opacity: 0; transform: translateY(-12px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes scToastOut {
        from { opacity: 1; transform: translateY(0); }
        to { opacity: 0; transform: translateY(-12px); }
      }
    `;
    document.head.appendChild(style);
  }

  // ─── Контейнер ───
  function getContainer() {
    let c = document.getElementById('sc-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'sc-toast-container';
      c.className = 'sc-toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  // ─── Конфіг винагород ───
  // chain = ВСЕ дає +1 chain. xp залежить від важливості.
  const REWARDS = {
    // ── Дрібні дії ──
    topic_used_correctly: {
      xp: 5, chain: 1, style: '',
      icon: '✅',
      phrases: [
        'Чудово! {topic} ✓',
        'Nailed it! {topic} ✓',
        'Точно в ціль 🎯',
        'Bingo! {topic} в роботі',
        'Так, ти знаєш {topic} 💪',
      ],
    },
    topic_error_corrected: {
      xp: 3, chain: 1, style: 'warning',
      icon: '💡',
      phrases: [
        'Learning > perfection 💪',
        'Помилки — це дані, не провал 🧠',
        'Кожна помилка зближує з вільною мовою',
        'Mistakes are reps for the brain 🏋️',
        'Тепер ти знаєш правильно ✨',
      ],
    },
    phrase_saved: {
      xp: 10, chain: 1, style: '',
      icon: '💎',
      phrases: [
        'One more phrase in your pocket 💎',
        'Ще одна фраза в твоїй картотеці',
        'Слова не зникають — вони множаться 📚',
        'Що в кишені — те в голові 🧠',
      ],
    },
    phrase_of_day_seen: {
      xp: 5, chain: 1, style: '',
      icon: '☀️',
      phrases: [
        'Daily dose of English ☀️',
        'Щоденна порція мови — є',
        'Crisp morning, fresh phrase 🌅',
        'One phrase a day keeps silence away 💬',
      ],
    },

    // ── Великі дії ──
    buddy_session: {
      xp: 20, chain: 1, style: '',
      icon: '🔥',
      phrases: [
        'You just spoke English in real life 🔥',
        'Це була реальна англійська 🔥',
        'Real talk = real progress 🚀',
        'Розмова — твій найкращий вчитель',
        'Brain just rewired itself 🧠⚡',
      ],
    },
    video_lesson_done: {
      xp: 30, chain: 1, style: '',
      icon: '🎬',
      phrases: [
        'You just leveled up your ears 👂',
        'Один урок ближче до вільного мовлення',
        'Native speakers don\'t scare you anymore 🦁',
        'Твої вуха звикають до мови',
        'Видео переварено мозком ✅',
      ],
    },
    table_read_aloud: {
      xp: 15, chain: 1, style: '',
      icon: '📖',
      phrases: [
        'Your grammar foundation is set 🧱',
        'Граматичний фундамент закладено',
        'Rules in your mouth, not just your eyes',
        'Тепер це звучить як твоя мова',
      ],
    },
    sentences_30_done: {
      xp: 25, chain: 1, style: '',
      icon: '🗣',
      phrases: [
        'Your tongue knows the pattern now 🗣',
        'Тепер язик знає патерн',
        '30 разів — і це твоє назавжди',
        'Автоматизм увімкнено ⚙️',
        'Pattern locked in 🔒',
      ],
    },

    // ── Спеціальні події ──
    topic_levelup: {
      xp: 40, chain: 1, style: 'success',
      icon: '🟢',
      phrases: [
        '{topic} засвоєно! Тема зелена 🟢',
        '{topic} mastered ✓ Welcome to next level',
        'Топік закрито! 🎉',
        '{topic} тепер автоматично ⚡',
      ],
    },
    chain_extended: {
      xp: 10, chain: 1, style: 'special',
      icon: '🔗',
      phrases: [
        'Chain тримається! День {days} поспіль',
        'Streak: {days} 🔥 Don\'t break it!',
        '{days} днів — ти на марафоні',
        'Discipline > motivation. Day {days}',
      ],
    },
    chain_record: {
      xp: 25, chain: 1, style: 'special',
      icon: '🏆',
      phrases: [
        'Новий рекорд! {days} днів 🏆',
        'Personal best: {days} days 🥇',
        'Ти перевершив сам себе! {days} днів',
      ],
    },
    trial_chain_done: {
      xp: 100, chain: 1, style: 'special',
      icon: '⭐',
      phrases: [
        'You\'re {steps} steps from full SpeakChain ⚡',
        'Ланка {n}/7 — є! Ще {steps} до фінішу',
        'Trial momentum: building up 🔋',
      ],
    },
    challenge_completed: {
      xp: 50, chain: 1, style: 'special',
      icon: '🏆',
      phrases: [
        'You showed up. That\'s what counts 🏆',
        'Челендж закрито! Ти в топ',
        'Reps over excuses — done ⚡',
      ],
    },
    custom_situation_done: {
      xp: 30, chain: 1, style: '',
      icon: '⭐',
      phrases: [
        'Своя ситуація — закрито 🎯',
        'You just prepared for life ⚡',
        'Real situation = real prep',
      ],
    },
  };

  // ─── Основна функція ───
  function showReward(action, params) {
    params = params || {};
    const cfg = REWARDS[action];
    if (!cfg) {
      console.warn('Unknown reward action:', action);
      return;
    }

    // Випадкова фраза + рандомний вибір UA/EN — вже змішані в списку
    const phraseTemplate = cfg.phrases[Math.floor(Math.random() * cfg.phrases.length)];
    const phrase = phraseTemplate
      .replace('{topic}', params.topic || '')
      .replace('{days}', params.days || '')
      .replace('{n}', params.n || '')
      .replace('{steps}', params.steps || '');

    const container = getContainer();
    const toast = document.createElement('div');
    toast.className = 'sc-toast' + (cfg.style ? ' ' + cfg.style : '');

    let rewardsHtml = '';
    if (cfg.chain) {
      rewardsHtml += `<span class="sc-toast-chain">🔗 +${cfg.chain} chain</span>`;
    }
    if (cfg.xp) {
      rewardsHtml += `<span class="sc-toast-xp">⚡ +${cfg.xp} XP</span>`;
    }

    toast.innerHTML = `
      <div class="sc-toast-icon">${cfg.icon}</div>
      <div class="sc-toast-body">
        <div class="sc-toast-rewards">${rewardsHtml}</div>
        <div class="sc-toast-phrase">${phrase}</div>
      </div>
    `;

    container.appendChild(toast);

    // Авто-зникнення через 2.8 секунди
    setTimeout(() => {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 280);
    }, 2800);

    // Якщо є user ID — відправляємо на backend для запису XP/chain
    const uid = window.Telegram?.WebApp?.initDataUnsafe?.user?.id;
    if (uid && cfg.xp) {
      fetch('https://speakchain-bot-production.up.railway.app/sc_reward', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          uid: uid,
          init_data: window.Telegram?.WebApp?.initData || '',
          action: action,
          xp: cfg.xp,
          chain: cfg.chain,
          params: params,
        })
      }).catch(() => {}); // мовчки якщо помилка — toast вже показано
    }
  }

  // Експортуємо
  window.showReward = showReward;
  window.scRewards = REWARDS;
})();
