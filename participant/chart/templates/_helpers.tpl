{{- /* (list $ text): fill in {registry} and {tag} from .Values.image. */ -}}
{{- define "eoapi.images" -}}
{{- $v := (index . 0).Values.image -}}
{{- index . 1 | replace "{registry}" $v.registry | replace "{tag}" $v.tag -}}
{{- end -}}

{{- /* nodeSelector + tolerations of the workshop node pool, if set. */ -}}
{{- define "eoapi.pool" -}}
{{- with .Values.nodeSelector }}
nodeSelector: {{ toJson . }}
{{- end }}
{{- with .Values.tolerations }}
tolerations: {{ toJson . }}
{{- end }}
{{- end -}}
