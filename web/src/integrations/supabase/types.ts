export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      ai_outputs: {
        Row: {
          case_id: string | null
          created_at: string
          id: string
          model: string | null
          module: string
          output: string | null
          owner_id: string
          project_id: string | null
          prompt: string
          sources: Json | null
          title: string
          tokens_used: number | null
          updated_at: string
        }
        Insert: {
          case_id?: string | null
          created_at?: string
          id?: string
          model?: string | null
          module: string
          output?: string | null
          owner_id: string
          project_id?: string | null
          prompt: string
          sources?: Json | null
          title: string
          tokens_used?: number | null
          updated_at?: string
        }
        Update: {
          case_id?: string | null
          created_at?: string
          id?: string
          model?: string | null
          module?: string
          output?: string | null
          owner_id?: string
          project_id?: string | null
          prompt?: string
          sources?: Json | null
          title?: string
          tokens_used?: number | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "ai_outputs_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
        ]
      }
      basvurular: {
        Row: {
          ad_soyad: string
          atanan_id: string | null
          created_at: string
          durum: string
          eposta: string | null
          hukuk_alani: string | null
          id: string
          konu: string
          notlar: string | null
          sohbet_ozeti: string | null
          telefon: string | null
          updated_at: string
        }
        Insert: {
          ad_soyad: string
          atanan_id?: string | null
          created_at?: string
          durum?: string
          eposta?: string | null
          hukuk_alani?: string | null
          id?: string
          konu: string
          notlar?: string | null
          sohbet_ozeti?: string | null
          telefon?: string | null
          updated_at?: string
        }
        Update: {
          ad_soyad?: string
          atanan_id?: string | null
          created_at?: string
          durum?: string
          eposta?: string | null
          hukuk_alani?: string | null
          id?: string
          konu?: string
          notlar?: string | null
          sohbet_ozeti?: string | null
          telefon?: string | null
          updated_at?: string
        }
        Relationships: []
      }
      calendar_events: {
        Row: {
          all_day: boolean
          case_id: string | null
          client_id: string | null
          color: string | null
          created_at: string
          description: string | null
          end_at: string | null
          event_type: string
          id: string
          location: string | null
          owner_id: string
          reminder_minutes: number | null
          start_at: string
          title: string
          updated_at: string
        }
        Insert: {
          all_day?: boolean
          case_id?: string | null
          client_id?: string | null
          color?: string | null
          created_at?: string
          description?: string | null
          end_at?: string | null
          event_type?: string
          id?: string
          location?: string | null
          owner_id: string
          reminder_minutes?: number | null
          start_at: string
          title: string
          updated_at?: string
        }
        Update: {
          all_day?: boolean
          case_id?: string | null
          client_id?: string | null
          color?: string | null
          created_at?: string
          description?: string | null
          end_at?: string | null
          event_type?: string
          id?: string
          location?: string | null
          owner_id?: string
          reminder_minutes?: number | null
          start_at?: string
          title?: string
          updated_at?: string
        }
        Relationships: []
      }
      call_settings: {
        Row: {
          after_hours_message: string | null
          ai_summary_enabled: boolean
          business_hours_end: string | null
          business_hours_start: string | null
          created_at: string
          greeting: string | null
          id: string
          updated_at: string
          user_id: string
          voicemail_enabled: boolean
        }
        Insert: {
          after_hours_message?: string | null
          ai_summary_enabled?: boolean
          business_hours_end?: string | null
          business_hours_start?: string | null
          created_at?: string
          greeting?: string | null
          id?: string
          updated_at?: string
          user_id: string
          voicemail_enabled?: boolean
        }
        Update: {
          after_hours_message?: string | null
          ai_summary_enabled?: boolean
          business_hours_end?: string | null
          business_hours_start?: string | null
          created_at?: string
          greeting?: string | null
          id?: string
          updated_at?: string
          user_id?: string
          voicemail_enabled?: boolean
        }
        Relationships: []
      }
      calls: {
        Row: {
          ai_sentiment: string | null
          ai_summary: string | null
          caller_name: string | null
          case_id: string | null
          client_id: string | null
          created_at: string
          direction: string
          duration_sec: number
          id: string
          notes: string | null
          owner_id: string
          phone: string
          recording_url: string | null
          started_at: string
          status: string
          tags: string[] | null
          updated_at: string
        }
        Insert: {
          ai_sentiment?: string | null
          ai_summary?: string | null
          caller_name?: string | null
          case_id?: string | null
          client_id?: string | null
          created_at?: string
          direction?: string
          duration_sec?: number
          id?: string
          notes?: string | null
          owner_id: string
          phone: string
          recording_url?: string | null
          started_at?: string
          status?: string
          tags?: string[] | null
          updated_at?: string
        }
        Update: {
          ai_sentiment?: string | null
          ai_summary?: string | null
          caller_name?: string | null
          case_id?: string | null
          client_id?: string | null
          created_at?: string
          direction?: string
          duration_sec?: number
          id?: string
          notes?: string | null
          owner_id?: string
          phone?: string
          recording_url?: string | null
          started_at?: string
          status?: string
          tags?: string[] | null
          updated_at?: string
        }
        Relationships: []
      }
      case_documents: {
        Row: {
          case_id: string | null
          client_id: string | null
          content_excerpt: string | null
          created_at: string
          doc_date: string | null
          doc_type: string | null
          file_name: string
          id: string
          mime_type: string | null
          notes: string | null
          owner_id: string
          size_bytes: number | null
          source: string
          storage_path: string
          sync_run_id: string | null
          tags: string[] | null
          updated_at: string
          uyap_birim: string | null
          uyap_file_no: string | null
        }
        Insert: {
          case_id?: string | null
          client_id?: string | null
          content_excerpt?: string | null
          created_at?: string
          doc_date?: string | null
          doc_type?: string | null
          file_name: string
          id?: string
          mime_type?: string | null
          notes?: string | null
          owner_id: string
          size_bytes?: number | null
          source?: string
          storage_path: string
          sync_run_id?: string | null
          tags?: string[] | null
          updated_at?: string
          uyap_birim?: string | null
          uyap_file_no?: string | null
        }
        Update: {
          case_id?: string | null
          client_id?: string | null
          content_excerpt?: string | null
          created_at?: string
          doc_date?: string | null
          doc_type?: string | null
          file_name?: string
          id?: string
          mime_type?: string | null
          notes?: string | null
          owner_id?: string
          size_bytes?: number | null
          source?: string
          storage_path?: string
          sync_run_id?: string | null
          tags?: string[] | null
          updated_at?: string
          uyap_birim?: string | null
          uyap_file_no?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "case_documents_case_id_fkey"
            columns: ["case_id"]
            isOneToOne: false
            referencedRelation: "cases"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "case_documents_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
        ]
      }
      case_search_queries: {
        Row: {
          created_at: string
          hit_count: number
          id: string
          last_used_at: string
          query_hash: string
          query_text: string
          result_case_ids: string[] | null
          result_payload: Json | null
        }
        Insert: {
          created_at?: string
          hit_count?: number
          id?: string
          last_used_at?: string
          query_hash: string
          query_text: string
          result_case_ids?: string[] | null
          result_payload?: Json | null
        }
        Update: {
          created_at?: string
          hit_count?: number
          id?: string
          last_used_at?: string
          query_hash?: string
          query_text?: string
          result_case_ids?: string[] | null
          result_payload?: Json | null
        }
        Relationships: []
      }
      cases: {
        Row: {
          case_no: string | null
          case_type: string | null
          client_id: string | null
          court: string | null
          created_at: string
          esas_no: string | null
          id: string
          next_hearing: string | null
          notes: string | null
          opened_at: string | null
          opponent: string | null
          owner_id: string
          status: string
          title: string
          updated_at: string
        }
        Insert: {
          case_no?: string | null
          case_type?: string | null
          client_id?: string | null
          court?: string | null
          created_at?: string
          esas_no?: string | null
          id?: string
          next_hearing?: string | null
          notes?: string | null
          opened_at?: string | null
          opponent?: string | null
          owner_id: string
          status?: string
          title: string
          updated_at?: string
        }
        Update: {
          case_no?: string | null
          case_type?: string | null
          client_id?: string | null
          court?: string | null
          created_at?: string
          esas_no?: string | null
          id?: string
          next_hearing?: string | null
          notes?: string | null
          opened_at?: string | null
          opponent?: string | null
          owner_id?: string
          status?: string
          title?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "cases_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
        ]
      }
      chat_conversations: {
        Row: {
          created_at: string
          id: string
          title: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          title?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          title?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      chat_messages: {
        Row: {
          content: string
          conversation_id: string
          created_at: string
          id: string
          role: string
          user_id: string
        }
        Insert: {
          content: string
          conversation_id: string
          created_at?: string
          id?: string
          role: string
          user_id: string
        }
        Update: {
          content?: string
          conversation_id?: string
          created_at?: string
          id?: string
          role?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "chat_messages_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "chat_conversations"
            referencedColumns: ["id"]
          },
        ]
      }
      clients: {
        Row: {
          address: string | null
          client_type: string
          created_at: string
          email: string | null
          full_name: string
          id: string
          national_id: string | null
          notes: string | null
          owner_id: string
          phone: string | null
          tax_id: string | null
          updated_at: string
        }
        Insert: {
          address?: string | null
          client_type?: string
          created_at?: string
          email?: string | null
          full_name: string
          id?: string
          national_id?: string | null
          notes?: string | null
          owner_id: string
          phone?: string | null
          tax_id?: string | null
          updated_at?: string
        }
        Update: {
          address?: string | null
          client_type?: string
          created_at?: string
          email?: string | null
          full_name?: string
          id?: string
          national_id?: string | null
          notes?: string | null
          owner_id?: string
          phone?: string | null
          tax_id?: string | null
          updated_at?: string
        }
        Relationships: []
      }
      legal_documents: {
        Row: {
          content: string
          created_at: string
          doc_type: string
          id: string
          metadata: Json | null
          parties: Json | null
          status: string
          title: string
          updated_at: string
          user_id: string
        }
        Insert: {
          content: string
          created_at?: string
          doc_type: string
          id?: string
          metadata?: Json | null
          parties?: Json | null
          status?: string
          title: string
          updated_at?: string
          user_id: string
        }
        Update: {
          content?: string
          created_at?: string
          doc_type?: string
          id?: string
          metadata?: Json | null
          parties?: Json | null
          status?: string
          title?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      mevzuat: {
        Row: {
          adi: string
          created_at: string
          id: string
          kaynak_url: string | null
          madde_listesi: Json
          metadata: Json | null
          mevzuat_id: string
          mevzuat_no: string | null
          resmi_gazete_sayisi: string | null
          resmi_gazete_tarihi: string | null
          tam_metin: string | null
          tertip: number | null
          tur: string | null
          updated_at: string
        }
        Insert: {
          adi: string
          created_at?: string
          id?: string
          kaynak_url?: string | null
          madde_listesi?: Json
          metadata?: Json | null
          mevzuat_id: string
          mevzuat_no?: string | null
          resmi_gazete_sayisi?: string | null
          resmi_gazete_tarihi?: string | null
          tam_metin?: string | null
          tertip?: number | null
          tur?: string | null
          updated_at?: string
        }
        Update: {
          adi?: string
          created_at?: string
          id?: string
          kaynak_url?: string | null
          madde_listesi?: Json
          metadata?: Json | null
          mevzuat_id?: string
          mevzuat_no?: string | null
          resmi_gazete_sayisi?: string | null
          resmi_gazete_tarihi?: string | null
          tam_metin?: string | null
          tertip?: number | null
          tur?: string | null
          updated_at?: string
        }
        Relationships: []
      }
      profiles: {
        Row: {
          avatar_url: string | null
          created_at: string
          first_name: string | null
          id: string
          last_name: string | null
          office_name: string | null
          phone: string | null
          updated_at: string
        }
        Insert: {
          avatar_url?: string | null
          created_at?: string
          first_name?: string | null
          id: string
          last_name?: string | null
          office_name?: string | null
          phone?: string | null
          updated_at?: string
        }
        Update: {
          avatar_url?: string | null
          created_at?: string
          first_name?: string | null
          id?: string
          last_name?: string | null
          office_name?: string | null
          phone?: string | null
          updated_at?: string
        }
        Relationships: []
      }
      project_notes: {
        Row: {
          content: string
          created_at: string
          id: string
          owner_id: string
          project_id: string
          title: string | null
          updated_at: string
        }
        Insert: {
          content: string
          created_at?: string
          id?: string
          owner_id: string
          project_id: string
          title?: string | null
          updated_at?: string
        }
        Update: {
          content?: string
          created_at?: string
          id?: string
          owner_id?: string
          project_id?: string
          title?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "project_notes_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
        ]
      }
      projects: {
        Row: {
          case_id: string | null
          client_id: string | null
          color: string | null
          created_at: string
          description: string | null
          id: string
          name: string
          owner_id: string
          status: string
          updated_at: string
        }
        Insert: {
          case_id?: string | null
          client_id?: string | null
          color?: string | null
          created_at?: string
          description?: string | null
          id?: string
          name: string
          owner_id: string
          status?: string
          updated_at?: string
        }
        Update: {
          case_id?: string | null
          client_id?: string | null
          color?: string | null
          created_at?: string
          description?: string | null
          id?: string
          name?: string
          owner_id?: string
          status?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "projects_case_id_fkey"
            columns: ["case_id"]
            isOneToOne: false
            referencedRelation: "cases"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "projects_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
        ]
      }
      reminders: {
        Row: {
          case_id: string | null
          channel: string
          created_at: string
          event_id: string | null
          id: string
          note: string | null
          owner_id: string
          remind_at: string
          status: string
          task_id: string | null
          title: string
          updated_at: string
        }
        Insert: {
          case_id?: string | null
          channel?: string
          created_at?: string
          event_id?: string | null
          id?: string
          note?: string | null
          owner_id: string
          remind_at: string
          status?: string
          task_id?: string | null
          title: string
          updated_at?: string
        }
        Update: {
          case_id?: string | null
          channel?: string
          created_at?: string
          event_id?: string | null
          id?: string
          note?: string | null
          owner_id?: string
          remind_at?: string
          status?: string
          task_id?: string | null
          title?: string
          updated_at?: string
        }
        Relationships: []
      }
      risk_analyses: {
        Row: {
          created_at: string
          findings: Json
          id: string
          recommendations: Json
          risk_level: string
          risk_score: number
          source_text: string
          summary: string | null
          title: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          findings?: Json
          id?: string
          recommendations?: Json
          risk_level?: string
          risk_score?: number
          source_text: string
          summary?: string | null
          title: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          findings?: Json
          id?: string
          recommendations?: Json
          risk_level?: string
          risk_score?: number
          source_text?: string
          summary?: string | null
          title?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      tasks: {
        Row: {
          assignee_id: string | null
          case_id: string | null
          created_at: string
          description: string | null
          due_date: string | null
          id: string
          owner_id: string
          priority: string
          status: string
          title: string
          updated_at: string
        }
        Insert: {
          assignee_id?: string | null
          case_id?: string | null
          created_at?: string
          description?: string | null
          due_date?: string | null
          id?: string
          owner_id: string
          priority?: string
          status?: string
          title: string
          updated_at?: string
        }
        Update: {
          assignee_id?: string | null
          case_id?: string | null
          created_at?: string
          description?: string | null
          due_date?: string | null
          id?: string
          owner_id?: string
          priority?: string
          status?: string
          title?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "tasks_case_id_fkey"
            columns: ["case_id"]
            isOneToOne: false
            referencedRelation: "cases"
            referencedColumns: ["id"]
          },
        ]
      }
      user_roles: {
        Row: {
          created_at: string
          id: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          role?: Database["public"]["Enums"]["app_role"]
          user_id?: string
        }
        Relationships: []
      }
      uyap_ingest_tokens: {
        Row: {
          created_at: string
          id: string
          label: string | null
          last_used_at: string | null
          owner_id: string
          revoked: boolean
          token: string
        }
        Insert: {
          created_at?: string
          id?: string
          label?: string | null
          last_used_at?: string | null
          owner_id: string
          revoked?: boolean
          token: string
        }
        Update: {
          created_at?: string
          id?: string
          label?: string | null
          last_used_at?: string | null
          owner_id?: string
          revoked?: boolean
          token?: string
        }
        Relationships: []
      }
      uyap_sync_runs: {
        Row: {
          archive_name: string | null
          created_at: string
          duration_ms: number | null
          error_message: string | null
          found_count: number
          id: string
          inserted_count: number
          owner_id: string
          skipped_count: number
          status: string
          updated_at: string
        }
        Insert: {
          archive_name?: string | null
          created_at?: string
          duration_ms?: number | null
          error_message?: string | null
          found_count?: number
          id?: string
          inserted_count?: number
          owner_id: string
          skipped_count?: number
          status?: string
          updated_at?: string
        }
        Update: {
          archive_name?: string | null
          created_at?: string
          duration_ms?: number | null
          error_message?: string | null
          found_count?: number
          id?: string
          inserted_count?: number
          owner_id?: string
          skipped_count?: number
          status?: string
          updated_at?: string
        }
        Relationships: []
      }
      yargitay_cases: {
        Row: {
          created_at: string
          daire: string
          esas_no: string
          excerpt: string | null
          full_text: string | null
          hukuk_dali: string | null
          id: string
          karar_no: string
          karar_tarihi: string | null
          keywords: string[] | null
          metadata: Json | null
          source: string
          source_url: string | null
          title: string | null
          updated_at: string
          verified: boolean
        }
        Insert: {
          created_at?: string
          daire: string
          esas_no: string
          excerpt?: string | null
          full_text?: string | null
          hukuk_dali?: string | null
          id?: string
          karar_no: string
          karar_tarihi?: string | null
          keywords?: string[] | null
          metadata?: Json | null
          source?: string
          source_url?: string | null
          title?: string | null
          updated_at?: string
          verified?: boolean
        }
        Update: {
          created_at?: string
          daire?: string
          esas_no?: string
          excerpt?: string | null
          full_text?: string | null
          hukuk_dali?: string | null
          id?: string
          karar_no?: string
          karar_tarihi?: string | null
          keywords?: string[] | null
          metadata?: Json | null
          source?: string
          source_url?: string | null
          title?: string | null
          updated_at?: string
          verified?: boolean
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      has_role: {
        Args: {
          _role: Database["public"]["Enums"]["app_role"]
          _user_id: string
        }
        Returns: boolean
      }
    }
    Enums: {
      app_role: "admin" | "lawyer" | "intern" | "secretary"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      app_role: ["admin", "lawyer", "intern", "secretary"],
    },
  },
} as const
