<script setup lang="ts">
const playerId = defineModel<number>('id', { default: 0 })
const emit = defineEmits<{ connect: [] }>()
</script>

<template>
  <div class="flex items-center gap-3">
    <select
      v-model.number="playerId"
      class="bg-slate-800/60 border border-slate-600/30 rounded-lg px-3 py-1.5 text-sm text-white focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500/30 transition-all appearance-none cursor-pointer"
      style="background-image: url('data:image/svg+xml;charset=UTF-8,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 20 20%22 fill=%22%2364748b%22%3E%3Cpath fill-rule=%22evenodd%22 d=%22M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z%22/%3E%3C/svg%3E'); background-position: right 8px center; background-repeat: no-repeat; background-size: 16px; padding-right: 28px;"
    >
      <option :value="0">旁观者 (0)</option>
      <option v-for="i in 9" :key="i" :value="i">{{ i }}号 玩家</option>
    </select>
    <button
      @click="emit('connect')"
      class="px-4 py-2 rounded-lg text-sm font-medium text-white bg-gradient-to-r from-indigo-700 to-indigo-500 hover:from-indigo-600 hover:to-indigo-400 shadow-md hover:shadow-lg transition-all duration-200"
    >
      连接
    </button>
  </div>
</template>