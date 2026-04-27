<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useGameStore } from './stores/gameStore'
import GameBoard from './components/GameBoard.vue'
import ChatLog from './components/ChatLog.vue'
import HumanInput from './components/HumanInput.vue'
import ConnectPanel from './components/ConnectPanel.vue'

const store = useGameStore()
const playerInputId = ref<number>(0)

const phaseLabel = computed(() => {
  const labels: Record<string, string> = {
    night: '夜晚',
    day_speech: '白天发言',
    day_vote: '投票',
    game_over: '游戏结束',
  }
  return labels[store.phase] || store.phase
})

const phaseIcon = computed(() => {
  const icons: Record<string, string> = {
    night: '🌙',
    day_speech: '☀️',
    day_vote: '⚖️',
    game_over: '🏆',
  }
  return icons[store.phase] || '•'
})

const bgGradient = computed(() => {
  switch (store.phase) {
    case 'night':
      return 'bg-gradient-to-b from-[#0f0a1a] via-[#1a1033] to-[#0f172a]'
    case 'day_speech':
      return 'bg-gradient-to-b from-[#1a1a0f] via-[#2a1f10] to-[#0f172a]'
    case 'day_vote':
      return 'bg-gradient-to-b from-[#1a0f0f] via-[#2a1510] to-[#0f172a]'
    case 'game_over':
      return 'bg-gradient-to-b from-[#0f1a0a] via-[#1a3320] to-[#0f172a]'
    default:
      return 'bg-gradient-to-b from-[#0f0a1a] via-[#1a1033] to-[#0f172a]'
  }
})

function handleConnect() {
  store.connect(playerInputId.value)
  if (playerInputId.value > 0) {
    store.fetchMyRole()
  }
}

onMounted(() => {
  store.fetchState()
})

onUnmounted(() => {
  store.disconnect()
})
</script>

<template>
  <div :class="bgGradient" class="min-h-screen flex flex-col transition-all duration-1000">
    <!-- Header -->
    <header class="glass-panel-dark flex-shrink-0 px-6 py-3 flex items-center justify-between mx-3 mt-3">
      <div class="flex items-center gap-4">
        <h1 class="text-xl font-bold text-white tracking-wide" style="font-family: 'Noto Serif SC', serif;">狼人杀博弈</h1>
        <div
          class="flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium transition-all duration-700"
          :class="{
            'bg-indigo-500/20 text-moonlight-light border border-indigo-500/30': store.phase === 'night',
            'bg-amber-500/20 text-amber-300 border border-amber-500/30': store.phase === 'day_speech',
            'bg-red-500/20 text-red-300 border border-red-500/30': store.phase === 'day_vote',
            'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30': store.phase === 'game_over',
          }"
        >
          <span class="animate-moon-float">{{ phaseIcon }}</span>
          <span>第{{ store.round }}轮 · {{ phaseLabel }}</span>
        </div>
      </div>

      <ConnectPanel v-if="!store.connected" @connect="handleConnect" v-model:id="playerInputId" />

      <div v-else class="flex items-center gap-3">
        <span class="text-sm text-slate-400">
          {{ store.isHumanPlayer ? `玩家 ${store.myPlayerId}号` : '旁观者' }}
        </span>
        <button
          v-if="store.gameStatus === 'not_started'"
          @click="store.startGame()"
          class="px-4 py-2 rounded-lg text-sm font-medium text-white btn-werewolf"
        >
          开始游戏
        </button>
        <button
          @click="store.disconnect()"
          class="px-3 py-1.5 bg-slate-800/60 hover:bg-slate-700/60 text-slate-400 rounded-lg text-sm border border-slate-700/30 transition-all"
        >
          断开
        </button>
      </div>
    </header>

    <!-- Player Board (fixed at top) -->
    <div class="flex-shrink-0 mx-3 glass-panel mt-2 transition-all duration-700">
      <GameBoard />
    </div>

    <!-- Role Info Banner -->
    <div
      v-if="store.myRoleInfo && store.isHumanPlayer"
      class="flex-shrink-0 mx-3 mt-2 glass-panel px-4 py-2"
      :class="{
        'role-border-werewolf': store.myRoleInfo.role === 'werewolf',
        'role-border-seer': store.myRoleInfo.role === 'seer',
        'role-border-witch': store.myRoleInfo.role === 'witch',
        'role-border-hunter': store.myRoleInfo.role === 'hunter',
        'role-border-villager': store.myRoleInfo.role === 'villager',
      }"
    >
      <div class="flex items-center gap-2">
        <div :class="{
          'role-badge-werewolf': store.myRoleInfo.role === 'werewolf',
          'role-badge-seer': store.myRoleInfo.role === 'seer',
          'role-badge-witch': store.myRoleInfo.role === 'witch',
          'role-badge-hunter': store.myRoleInfo.role === 'hunter',
          'role-badge-villager': store.myRoleInfo.role === 'villager',
        }" class="role-badge text-xs">
          {{ store.roleNameMap[store.myRoleInfo.role]?.charAt(0) }}
        </div>
        <span class="font-bold" :class="store.roleColorMap[store.myRoleInfo.role]">
          {{ store.myPlayerId }}号 · {{ store.roleNameMap[store.myRoleInfo.role] }}
        </span>
        <span class="text-sm text-slate-400">({{ store.myRoleInfo.personality }})</span>
      </div>
      <div v-if="store.myRoleInfo.werewolf_peers" class="text-sm text-red-400 mt-1">
        同伴: {{ store.myRoleInfo.werewolf_peers.join(', ') }}号
      </div>
      <div v-if="store.myRoleInfo.seer_checks?.length" class="text-sm text-cyan-400 mt-1">
        查验记录:
        <span v-for="c in store.myRoleInfo.seer_checks" :key="c.target_id">
          {{ c.target_id }}号={{ c.is_werewolf ? '狼人' : '好人' }}
        </span>
      </div>
    </div>

    <!-- Chat Log + Human Input (scrollable bottom area) -->
    <div class="flex-1 flex flex-col min-h-0 overflow-hidden mx-3 mt-2 mb-3 gap-2">
      <ChatLog class="flex-1 min-h-0" />
      <HumanInput v-if="store.hasPendingAction" />
    </div>
  </div>
</template>