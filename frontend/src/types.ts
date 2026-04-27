export type Role = 'werewolf' | 'seer' | 'witch' | 'hunter' | 'villager'
export type Phase = 'night' | 'day_speech' | 'day_vote' | 'game_over'
export type LifeStatus = 'alive' | 'dead'
export type PlayerType = 'llm' | 'human'

export interface PlayerPublic {
  id: number
  role: Role
  life_status: LifeStatus
  personality: string
  player_type: PlayerType
}

export interface PlayerFull extends PlayerPublic {
  faction: string
  is_alive: boolean
  werewolf_peers?: number[]
  seer_checks?: { target_id: number; is_werewolf: boolean }[]
}

export interface GameEvent {
  type: string
  data: Record<string, unknown>
  timestamp: number
}

export interface ActionRequest {
  request_id: string
  action_type: 'night_action' | 'speech' | 'vote' | 'hunter_shoot'
  role: Role
  prompt: string
  options: number[]
  context: string
}

export interface GameStatePublic {
  status: 'running' | 'ended' | 'not_started'
  round: number
  phase: Phase
  players: PlayerPublic[]
  alive_ids: number[]
  public_history: string[]
}