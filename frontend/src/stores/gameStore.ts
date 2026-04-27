import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PlayerPublic, PlayerFull, GameEvent, ActionRequest, Phase, Role } from '../types'

export const useGameStore = defineStore('game', () => {
  // ─── State ───
  const players = ref<PlayerPublic[]>([])
  const myPlayerId = ref<number | null>(null)
  const myRoleInfo = ref<PlayerFull | null>(null)
  const phase = ref<Phase>('night')
  const round = ref(1)
  const events = ref<GameEvent[]>([])
  const pendingAction = ref<ActionRequest | null>(null)
  const gameStatus = ref<'not_started' | 'running' | 'ended'>('not_started')
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)

  // ─── Computed ───
  const aliveIds = computed(() => players.value.filter(p => p.life_status === 'alive').map(p => p.id))
  const isHumanPlayer = computed(() => myPlayerId.value !== null && myPlayerId.value > 0)
  const hasPendingAction = computed(() => pendingAction.value !== null)

  const roleColorMap: Record<Role, string> = {
    werewolf: 'text-red-500',
    seer: 'text-cyan-400',
    witch: 'text-fuchsia-400',
    hunter: 'text-yellow-400',
    villager: 'text-green-400',
  }

  const roleNameMap: Record<Role, string> = {
    werewolf: '狼人',
    seer: '预言家',
    witch: '女巫',
    hunter: '猎人',
    villager: '村民',
  }

  // ─── Actions ───
  function addEvent(type: string, data: Record<string, unknown>) {
    events.value.push({ type, data, timestamp: Date.now() })
  }

  function connect(playerId: number) {
    myPlayerId.value = playerId
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    // 开发环境直接连8000，生产环境走代理
    const wsUrl = import.meta.env.DEV
      ? `ws://localhost:8000/ws/game/${playerId}`
      : `${protocol}//${host}/ws/game/${playerId}`

    const socket = new WebSocket(wsUrl)

    socket.onopen = () => {
      connected.value = true
      addEvent('system', { message: 'WebSocket 已连接' })
    }

    socket.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        handleWSMessage(msg)
      } catch {
        console.error('Failed to parse WS message', e.data)
      }
    }

    socket.onclose = () => {
      connected.value = false
      addEvent('system', { message: 'WebSocket 已断开' })
    }

    socket.onerror = () => {
      addEvent('system', { message: 'WebSocket 连接错误' })
    }

    ws.value = socket
  }

  function handleWSMessage(msg: { type: string; data: Record<string, unknown> }) {
    const { type, data } = msg

    switch (type) {
      case 'action_request':
        // 人类玩家的行动请求
        pendingAction.value = data as unknown as ActionRequest
        addEvent('action_request', data)
        break

      case 'night_start':
        phase.value = 'night'
        round.value = (data.round as number) || round.value
        addEvent('night_start', data)
        break

      case 'progress':
        addEvent('progress', data)
        // 从进度事件同步 phase 和 round
        if (data.phase) phase.value = data.phase as Phase
        if (data.round) round.value = data.round as number
        break

      case 'night_result':
        addEvent('night_result', data)
        // 更新死亡状态
        const deaths = (data.deaths as number[]) || []
        deaths.forEach(id => {
          const p = players.value.find(p => p.id === id)
          if (p) p.life_status = 'dead'
        })
        break

      case 'day_speech_start':
        phase.value = 'day_speech'
        round.value = (data.round as number) || round.value
        addEvent('day_speech_start', data)
        break

      case 'player_speech':
        addEvent('player_speech', data)
        break

      case 'day_vote_start':
        phase.value = 'day_vote'
        addEvent('day_vote_start', data)
        break

      case 'player_vote':
        addEvent('player_vote', data)
        break

      case 'vote_result':
        const eliminated = data.eliminated_id as number | null
        if (eliminated) {
          const p = players.value.find(p => p.id === eliminated)
          if (p) p.life_status = 'dead'
        }
        addEvent('vote_result', data)
        break

      case 'hunter_shoot':
        addEvent('hunter_shoot', data)
        const target = data.target as number
        const tp = players.value.find(p => p.id === target)
        if (tp) tp.life_status = 'dead'
        break

      case 'seer_check_public':
        addEvent('seer_check_public', data)
        break

      case 'seer_check_private':
        // 私密查验结果——仅预言家收到
        addEvent('seer_check_private', data)
        if (myRoleInfo.value) {
          myRoleInfo.value.seer_checks = myRoleInfo.value.seer_checks || []
          myRoleInfo.value.seer_checks.push({
            target_id: data.target as number,
            is_werewolf: data.is_werewolf as boolean,
          })
        }
        break

      case 'game_over':
        phase.value = 'game_over'
        gameStatus.value = 'ended'
        // 游戏结束揭示所有角色
        const gameOverPlayers = data.players as Array<{
          id: number; role: string; life_status: string; player_type: string
        }>
        if (gameOverPlayers) {
          players.value = players.value.map(p => {
            const full = gameOverPlayers.find(fp => fp.id === p.id)
            if (full) {
              return { ...p, role: full.role as any, life_status: full.life_status as any }
            }
            return p
          })
        }
        addEvent('game_over', data)
        break

      case 'game_reset':
        // 游戏重置：清空状态，等待新游戏
        phase.value = 'night'
        round.value = 1
        gameStatus.value = 'not_started'
        events.value = []
        pendingAction.value = null
        players.value = []
        myRoleInfo.value = null
        addEvent('system', { message: data.message as string || '游戏已重置' })
        break

      case 'waiting_for_player':
        addEvent('waiting_for_player', data)
        break

      default:
        addEvent(type, data)
    }
  }

  function submitAction(actionData: Record<string, unknown>) {
    if (!ws.value || !pendingAction.value) return

    const msg = {
      type: 'action_response',
      data: {
        request_id: pendingAction.value.request_id,
        action_type: pendingAction.value.action_type,
        ...actionData,
      },
    }
    ws.value.send(JSON.stringify(msg))
    pendingAction.value = null
  }

  async function fetchState() {
    try {
      const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
      const res = await fetch(`${baseUrl}/api/state`)
      const state = await res.json()
      if (state.status !== 'not_started') {
        gameStatus.value = state.status as any
        round.value = state.round
        phase.value = state.phase as Phase
        players.value = state.players
      }
    } catch (e) {
      console.error('Failed to fetch state', e)
    }
  }

  async function fetchMyRole() {
    if (!myPlayerId.value || myPlayerId.value === 0) return
    try {
      const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
      const res = await fetch(`${baseUrl}/api/my-role/${myPlayerId.value}`)
      myRoleInfo.value = await res.json()
    } catch (e) {
      console.error('Failed to fetch role', e)
    }
  }

  async function startGame() {
    try {
      const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
      await fetch(`${baseUrl}/api/game/start`, { method: 'POST' })
      gameStatus.value = 'running'
      await fetchState()
      await fetchMyRole()
    } catch (e) {
      console.error('Failed to start game', e)
    }
  }

  async function restartGame() {
    try {
      const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
      await fetch(`${baseUrl}/api/game/restart`, { method: 'POST' })
      gameStatus.value = 'not_started'
      phase.value = 'night'
      round.value = 1
      events.value = []
      pendingAction.value = null
      myRoleInfo.value = null
      // 等一下让后端完成重置，然后刷新状态
      await new Promise(r => setTimeout(r, 500))
      await fetchState()
    } catch (e) {
      console.error('Failed to restart game', e)
    }
  }

  async function stopGame() {
    try {
      const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
      await fetch(`${baseUrl}/api/game/stop`, { method: 'POST' })
    } catch (e) {
      console.error('Failed to stop game', e)
    }
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
  }

  return {
    players, myPlayerId, myRoleInfo, phase, round, events,
    pendingAction, gameStatus, connected, ws,
    aliveIds, isHumanPlayer, hasPendingAction,
    roleColorMap, roleNameMap,
    connect, submitAction, fetchState, fetchMyRole, startGame, restartGame, stopGame, disconnect, addEvent,
  }
})