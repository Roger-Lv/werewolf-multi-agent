<script setup lang="ts">
import { useGameStore } from '../stores/gameStore'
import { ref, nextTick, watch, computed } from 'vue'
import type { GameEvent } from '../types'

const store = useGameStore()
const logContainer = ref<HTMLElement | null>(null)

// Auto-scroll to bottom on new events
watch(() => store.events.length, async () => {
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})

function eventIcon(type: string): string {
  const icons: Record<string, string> = {
    system: '🔌',
    progress: '⏳',
    game_reset: '🔄',
    night_start: '🌙',
    night_result: '💀',
    seer_check_public: '🔍',
    seer_check_private: '🔎',
    day_speech_start: '☀️',
    player_speech: '💬',
    day_vote_start: '⚖️',
    player_vote: '👆',
    vote_result: '⚖️',
    hunter_shoot: '🏹',
    game_over: '🏆',
    waiting_for_player: '⏳',
    action_request: '❓',
  }
  return icons[type] || '•'
}

function eventCardClass(type: string): string {
  const classes: Record<string, string> = {
    progress: 'progress-bar',
    game_reset: 'border-l-3 border-emerald-500/40 bg-emerald-950/30',
    night_start: 'border-l-3 border-indigo-500/40 bg-indigo-950/30',
    night_result: 'border-l-3 border-red-500/40 bg-red-950/20',
    seer_check_public: 'border-l-3 border-cyan-500/30 bg-cyan-950/20',
    seer_check_private: 'border-l-3 border-cyan-400/60 bg-cyan-950/30',
    day_speech_start: 'border-l-3 border-amber-500/40 bg-amber-950/20',
    player_speech: 'border-l-3 border-amber-400/30 bg-amber-950/10',
    day_vote_start: 'border-l-3 border-red-400/40 bg-red-950/20',
    player_vote: 'border-l-3 border-red-300/30 bg-red-950/10',
    vote_result: 'border-l-3 border-orange-500/50 bg-orange-950/20',
    hunter_shoot: 'border-l-3 border-yellow-500/40 bg-yellow-950/20',
    game_over: 'border-l-3 border-emerald-500/50 bg-emerald-950/20',
    system: 'border-l-3 border-slate-500/30 bg-slate-950/40',
    action_request: 'border-l-3 border-indigo-400/50 bg-indigo-950/30',
    waiting_for_player: 'border-l-3 border-slate-400/30 bg-slate-950/30',
  }
  return classes[type] || 'border-l-3 border-slate-600/30 bg-slate-950/30'
}

// Deduplicate consecutive identical progress messages
const dedupedEvents = computed(() => {
  const result: GameEvent[] = []
  for (const event of store.events) {
    // Skip if previous event is the same progress message
    if (event.type === 'progress' && result.length > 0) {
      const prev = result[result.length - 1]
      if (prev.type === 'progress' && prev.data.message === event.data.message) {
        // Update detail instead of adding duplicate
        result[result.length - 1] = event
        continue
      }
    }
    result.push(event)
  }
  return result
})

// Detect phase transitions for divider markers
const phaseDividers = computed(() => {
  const dividers: { index: number; label: string; icon: string }[] = []
  const events = dedupedEvents.value
  for (let i = 1; i < events.length; i++) {
    const curr = events[i]
    // Night start → divider
    if (curr.type === 'night_start') {
      dividers.push({ index: i, label: `第${curr.data.round || '?'}夜`, icon: '🌙' })
    }
    // Day speech start → divider
    if (curr.type === 'day_speech_start') {
      dividers.push({ index: i, label: `第${curr.data.round || '?'}天`, icon: '☀️' })
    }
  }
  return dividers
})
</script>

<template>
  <div ref="logContainer" class="glass-panel-dark overflow-y-auto p-4 rounded-lg">
    <h2 class="text-sm font-semibold text-slate-500 mb-3 sticky top-0 bg-[rgba(10,10,26,0.9)] pb-2 backdrop-blur-sm z-10">
      事件日志
    </h2>

    <div class="space-y-1.5">
      <template v-for="(event, idx) in dedupedEvents" :key="idx">
        <!-- Phase divider -->
        <div
          v-for="divider in phaseDividers.filter(d => d.index === idx)"
          :key="'d-'+idx"
          class="phase-divider my-2"
        >
          <span>{{ divider.icon }} {{ divider.label }}</span>
        </div>

        <!-- Event card -->
        <div
          class="rounded-lg px-3 py-2 text-sm animate-fade-in-up transition-all"
          :class="eventCardClass(event.type)"
        >
          <div class="flex items-start gap-2.5">
            <span
              class="text-base flex-shrink-0 mt-0.5"
              :class="event.type === 'progress' ? 'animate-pulse-glow' : ''"
            >{{ eventIcon(event.type) }}</span>
            <div class="flex-1 min-w-0">
              <!-- Progress -->
              <template v-if="event.type === 'progress'">
                <span class="text-slate-300">{{ event.data.message }}</span>
                <div v-if="event.data.detail" class="text-xs text-slate-500 mt-1 leading-relaxed whitespace-pre-wrap">{{ event.data.detail }}</div>
              </template>

              <!-- System -->
              <template v-if="event.type === 'system'">
                <span class="text-slate-500 italic">{{ event.data.message }}</span>
              </template>

              <!-- Game reset -->
              <template v-if="event.type === 'game_reset'">
                <span class="text-emerald-300 font-medium">{{ event.data.message }}</span>
              </template>

              <!-- Night start -->
              <template v-if="event.type === 'night_start'">
                <span class="text-indigo-300 font-medium">夜幕降临，各角色行动中...</span>
              </template>

              <!-- Night result -->
              <template v-if="event.type === 'night_result'">
                <div class="text-red-300 font-medium">{{ event.data.announcement }}</div>
                <div v-if="(event.data.deaths as number[])?.length" class="text-red-400/70 text-xs mt-1">
                  死亡: {{ (event.data.deaths as number[]).join(', ') }}号
                </div>
              </template>

              <!-- Seer check private -->
              <template v-if="event.type === 'seer_check_private'">
                <div class="text-cyan-300">
                  查验结果: {{ event.data.target }}号 →
                  <span :class="event.data.is_werewolf ? 'text-red-400' : 'text-green-400'">
                    {{ event.data.is_werewolf ? '狼人' : '好人' }}
                  </span>
                </div>
              </template>

              <!-- Speech -->
              <template v-if="event.type === 'player_speech'">
                <div class="flex items-baseline gap-2">
                  <span class="font-bold text-amber-200">{{ event.data.player_id }}号:</span>
                  <span class="text-slate-300 leading-relaxed">{{ event.data.content }}</span>
                </div>
              </template>

              <!-- Vote -->
              <template v-if="event.type === 'player_vote'">
                <span class="text-red-300">{{ event.data.voter }}号 → {{ event.data.target }}号</span>
              </template>

              <!-- Vote result -->
              <template v-if="event.type === 'vote_result'">
                <div class="text-orange-300 font-medium">{{ event.data.announcement }}</div>
              </template>

              <!-- Hunter shoot -->
              <template v-if="event.type === 'hunter_shoot'">
                <span class="text-yellow-300">猎人 {{ event.data.hunter }}号 开枪带走 {{ event.data.target }}号</span>
              </template>

              <!-- Game over -->
              <template v-if="event.type === 'game_over'">
                <div class="text-lg font-bold animate-pulse-glow" :class="event.data.winner === 'werewolf' ? 'text-red-400' : 'text-emerald-400'">
                  {{ event.data.winner === 'werewolf' ? '狼人阵营获胜！' : '好人阵营获胜！' }}
                </div>
                <div v-if="event.data.reason_text" class="text-sm mt-1 opacity-70" :class="event.data.winner === 'werewolf' ? 'text-red-300' : 'text-emerald-300'">
                  {{ event.data.reason_text }}
                </div>
              </template>

              <!-- Waiting -->
              <template v-if="event.type === 'waiting_for_player'">
                <span class="text-slate-400 animate-pulse-glow">等待 {{ event.data.player_id }}号 玩家行动...</span>
              </template>

              <!-- Default -->
              <template v-if="!['system','game_reset','progress','night_start','night_result','seer_check_private','player_speech','player_vote','vote_result','hunter_shoot','game_over','waiting_for_player'].includes(event.type)">
                <span class="text-slate-400">{{ JSON.stringify(event.data) }}</span>
              </template>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>