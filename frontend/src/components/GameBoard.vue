<script setup lang="ts">
import { useGameStore } from '../stores/gameStore'
import type { Role } from '../types'

const store = useGameStore()

const roleConfig: Record<Role, { name: string; color: string; badge: string; symbol: string; border: string }> = {
  werewolf:   { name: '狼人',   color: 'text-red-400',   badge: 'role-badge-werewolf',   symbol: '狼', border: 'role-border-werewolf' },
  seer:       { name: '预言家', color: 'text-cyan-400',  badge: 'role-badge-seer',       symbol: '预', border: 'role-border-seer' },
  witch:      { name: '女巫',   color: 'text-fuchsia-400', badge: 'role-badge-witch',   symbol: '巫', border: 'role-border-witch' },
  hunter:     { name: '猎人',   color: 'text-yellow-400', badge: 'role-badge-hunter',    symbol: '猎', border: 'role-border-hunter' },
  villager:   { name: '村民',   color: 'text-green-400',  badge: 'role-badge-villager',   symbol: '村', border: 'role-border-villager' },
}

function getRoleCfg(role: Role) {
  return roleConfig[role] || roleConfig.villager
}
</script>

<template>
  <div
    class="grid grid-cols-3 gap-2 py-2 px-2 transition-all duration-700"
    :class="store.phase === 'night' ? 'bg-indigo-950/30' : store.phase === 'day_speech' ? 'bg-amber-950/20' : store.phase === 'day_vote' ? 'bg-red-950/20' : 'bg-slate-950/20'"
  >
    <div
      v-for="player in store.players"
      :key="player.id"
      class="relative rounded-lg p-2.5 transition-all duration-500"
      :class="[
        player.life_status === 'alive'
          ? [getRoleCfg(player.role).border, 'bg-slate-900/60 hover:bg-slate-800/60']
          : ['border border-slate-800/50 bg-slate-950/60 opacity-40 death-overlay'],
        player.id === store.myPlayerId && player.life_status === 'alive' ? 'animate-glow-ring' : '',
      ]"
    >
      <!-- Death cross mark -->
      <div v-if="player.life_status === 'dead'" class="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
        <span class="text-red-500/80 text-2xl font-bold select-none">✕</span>
      </div>

      <div class="flex items-center gap-2">
        <!-- Role badge -->
        <div
          :class="player.life_status === 'alive' ? getRoleCfg(player.role).badge : 'bg-slate-800 role-badge'"
          class="role-badge transition-all duration-500"
        >
          <span v-if="player.life_status === 'alive'" class="select-none">{{ getRoleCfg(player.role).symbol }}</span>
          <span v-else class="text-slate-600 select-none">亡</span>
        </div>

        <!-- Info -->
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5">
            <span class="font-bold text-sm" :class="player.life_status === 'alive' ? 'text-white' : 'text-slate-500'">
              {{ player.id }}号
            </span>
            <span :class="player.life_status === 'alive' ? getRoleCfg(player.role).color : 'text-slate-600'" class="text-sm">
              {{ getRoleCfg(player.role).name }}
            </span>
          </div>
          <!-- Type + personality -->
          <div class="flex items-center gap-1.5 mt-0.5">
            <span
              class="text-xs px-1.5 py-0.5 rounded-full"
              :class="player.player_type === 'human' ? 'bg-emerald-900/40 text-emerald-400 border border-emerald-700/30' : 'bg-slate-800/60 text-slate-500 border border-slate-700/30'"
            >
              {{ player.player_type === 'human' ? '人' : 'AI' }}
            </span>
            <span v-if="player.life_status === 'alive'" class="text-xs text-slate-500 truncate">{{ player.personality }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>