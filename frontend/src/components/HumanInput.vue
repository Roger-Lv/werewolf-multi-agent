<script setup lang="ts">
import { ref, computed } from 'vue'
import { useGameStore } from '../stores/gameStore'
import type { Role } from '../types'

const store = useGameStore()
const selectedTarget = ref<number | null>(null)
const speechText = ref('')
const witchUseSave = ref(false)
const witchSaveTarget = ref<number | null>(null)
const witchUsePoison = ref(false)
const witchPoisonTarget = ref<number | null>(null)

const action = computed(() => store.pendingAction)

const targetOptions = computed(() => {
  if (!action.value) return []
  return action.value.options.map(id => ({
    id,
    player: store.players.find(p => p.id === id),
  }))
})

function getRoleLabel(): string {
  if (!action.value) return ''
  const labels: Record<Role, string> = {
    werewolf: '狼人',
    seer: '预言家',
    witch: '女巫',
    hunter: '猎人',
    villager: '村民',
  }
  return labels[action.value.role] || action.value.role
}

const roleButtonClass = computed(() => {
  if (!action.value) return ''
  const map: Record<Role, string> = {
    werewolf: 'btn-werewolf',
    seer: 'btn-seer',
    witch: 'btn-witch',
    hunter: 'btn-hunter',
    villager: 'btn-villager',
  }
  return map[action.value.role] || 'bg-indigo-600'
})

const roleBorderClass = computed(() => {
  if (!action.value) return ''
  const map: Record<Role, string> = {
    werewolf: 'role-border-werewolf',
    seer: 'role-border-seer',
    witch: 'role-border-witch',
    hunter: 'role-border-hunter',
    villager: 'role-border-villager',
  }
  return map[action.value.role] || 'border-indigo-600'
})

function submit() {
  if (!action.value) return

  switch (action.value.action_type) {
    case 'night_action':
      if (action.value.role === 'werewolf') {
        store.submitAction({ target_id: selectedTarget.value })
      } else if (action.value.role === 'seer') {
        store.submitAction({ target_id: selectedTarget.value })
      } else if (action.value.role === 'witch') {
        store.submitAction({
          use_save: witchUseSave.value,
          save_target_id: witchSaveTarget.value,
          use_poison: witchUsePoison.value,
          poison_target_id: witchPoisonTarget.value,
        })
      } else {
        store.submitAction({ action: 'sleep' })
      }
      break
    case 'speech':
      store.submitAction({ speech: speechText.value, thinking: '' })
      break
    case 'vote':
      store.submitAction({ vote_target: selectedTarget.value })
      break
    case 'hunter_shoot':
      store.submitAction({ shoot_target_id: selectedTarget.value })
      break
  }

  selectedTarget.value = null
  speechText.value = ''
  witchUseSave.value = false
  witchUsePoison.value = false
}
</script>

<template>
  <div v-if="action" class="glass-panel p-4" :class="roleBorderClass">
    <div class="flex items-center gap-3 mb-3">
      <div :class="{
        'role-badge-werewolf': action.role === 'werewolf',
        'role-badge-seer': action.role === 'seer',
        'role-badge-witch': action.role === 'witch',
        'role-badge-hunter': action.role === 'hunter',
        'role-badge-villager': action.role === 'villager',
      }" class="role-badge">
        {{ getRoleLabel().charAt(0) }}
      </div>
      <h3 class="text-sm font-bold text-white">你的行动</h3>
      <span class="text-xs px-2 py-0.5 rounded-full bg-slate-800/60 text-slate-400 border border-slate-700/30">
        {{ action.action_type === 'night_action' ? '夜晚行动' : action.action_type === 'speech' ? '发言' : action.action_type === 'vote' ? '投票' : '猎人开枪' }}
      </span>
    </div>

    <p v-if="action.prompt" class="text-sm text-slate-400 mb-3 leading-relaxed">{{ action.prompt }}</p>

    <!-- Target Selection (werewolf/seer/vote/hunter) -->
    <template v-if="(action.action_type === 'night_action' && (action.role === 'werewolf' || action.role === 'seer')) || action.action_type === 'vote' || action.action_type === 'hunter_shoot'">
      <div class="grid grid-cols-3 gap-2 mb-3">
        <button
          v-for="opt in targetOptions"
          :key="opt.id"
          @click="selectedTarget = opt.id"
          class="relative rounded-lg p-2.5 text-sm font-medium transition-all duration-200 group"
          :class="selectedTarget === opt.id
            ? [roleButtonClass, 'text-white ring-2 ring-white/30 scale-105']
            : 'bg-slate-800/60 text-slate-400 hover:bg-slate-700/60 border border-slate-700/30'"
        >
          <div class="flex flex-col items-center gap-1">
            <span class="text-lg font-bold">{{ opt.id }}</span>
            <span class="text-xs">{{ opt.player?.personality || '玩家' }}</span>
            <span v-if="opt.player?.life_status === 'dead'" class="text-xs text-red-400/60">已亡</span>
          </div>
        </button>
      </div>
      <button
        @click="submit"
        :disabled="!selectedTarget"
        class="w-full px-4 py-2.5 rounded-lg text-sm font-medium text-white transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
        :class="[roleButtonClass, selectedTarget ? 'hover:shadow-lg' : '']"
      >
        确认选择
      </button>
    </template>

    <!-- Witch Night Action -->
    <template v-if="action.action_type === 'night_action' && action.role === 'witch'">
      <div class="space-y-3 mb-3">
        <div class="rounded-lg p-3 border border-green-500/20 bg-green-950/20">
          <label class="flex items-center gap-2 text-sm cursor-pointer group">
            <input type="checkbox" v-model="witchUseSave" class="rounded accent-green-500" />
            <span class="text-green-400 group-hover:text-green-300 transition-colors">💚 使用解药救人</span>
          </label>
          <div v-if="witchUseSave" class="grid grid-cols-3 gap-2 mt-2">
            <button
              v-for="opt in targetOptions"
              :key="'save-'+opt.id"
              @click="witchSaveTarget = opt.id"
              class="rounded-lg p-2 text-xs font-medium transition-all"
              :class="witchSaveTarget === opt.id ? 'bg-green-600 text-white ring-2 ring-green-400/30' : 'bg-slate-800/60 text-slate-400 border border-slate-700/30'"
            >
              <div class="flex flex-col items-center gap-0.5">
                <span class="font-bold">{{ opt.id }}</span>
                <span>{{ opt.player?.personality }}</span>
              </div>
            </button>
          </div>
        </div>

        <div class="rounded-lg p-3 border border-fuchsia-500/20 bg-fuchsia-950/20">
          <label class="flex items-center gap-2 text-sm cursor-pointer group">
            <input type="checkbox" v-model="witchUsePoison" :disabled="witchUseSave" class="rounded accent-fuchsia-500" />
            <span class="text-fuchsia-400 group-hover:text-fuchsia-300 transition-colors">☠️ 使用毒药</span>
          </label>
          <div v-if="witchUsePoison" class="grid grid-cols-3 gap-2 mt-2">
            <button
              v-for="opt in targetOptions"
              :key="'poison-'+opt.id"
              @click="witchPoisonTarget = opt.id"
              class="rounded-lg p-2 text-xs font-medium transition-all"
              :class="witchPoisonTarget === opt.id ? 'bg-fuchsia-600 text-white ring-2 ring-fuchsia-400/30' : 'bg-slate-800/60 text-slate-400 border border-slate-700/30'"
            >
              <div class="flex flex-col items-center gap-0.5">
                <span class="font-bold">{{ opt.id }}</span>
                <span>{{ opt.player?.personality }}</span>
              </div>
            </button>
          </div>
          <p v-if="witchUseSave && witchUsePoison" class="text-xs text-red-400 mt-1">
            同一夜不能同时使用解药和毒药！
          </p>
        </div>
      </div>
      <button
        @click="submit"
        :disabled="witchUseSave && witchUsePoison"
        class="w-full px-4 py-2.5 rounded-lg text-sm font-medium text-white btn-witch transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        确认行动
      </button>
    </template>

    <!-- Villager Sleep -->
    <template v-if="action.action_type === 'night_action' && action.role === 'villager'">
      <button @click="submit" class="w-full px-4 py-2.5 rounded-lg text-sm text-slate-400 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/30 transition-all">
        夜晚无行动，继续睡觉
      </button>
    </template>

    <!-- Speech -->
    <template v-if="action.action_type === 'speech'">
      <textarea
        v-model="speechText"
        placeholder="请发表你的观点..."
        rows="3"
        class="w-full bg-slate-800/60 border border-slate-600/30 rounded-lg p-3 text-sm text-white placeholder-slate-500 resize-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/30 transition-all"
      ></textarea>
      <button
        @click="submit"
        :disabled="!speechText.trim()"
        class="w-full mt-2 px-4 py-2.5 rounded-lg text-sm font-medium text-white btn-hunter transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        发送发言
      </button>
    </template>
  </div>
</template>