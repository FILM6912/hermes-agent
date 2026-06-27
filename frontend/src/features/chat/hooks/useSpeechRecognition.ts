import { useEffect, useRef, useState, useCallback } from "react";

interface UseSpeechRecognitionProps {
  language: string;
  input: string;
  setInput: (value: string) => void;
}

export const useSpeechRecognition = ({
  language: _language,
  input,
  setInput,
}: UseSpeechRecognitionProps) => {
  const [isListening, setIsListening] = useState(false);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);
  const isActiveRef = useRef(false);
  const baseInputRef = useRef("");
  const setInputRef = useRef(setInput);
  const lastSpeechInputRef = useRef("");
  const isUpdatingFromSpeechRef = useRef(false);
  const processedResultsCountRef = useRef(0); // Track how many results we've processed

  // Keep setInput ref updated
  useEffect(() => {
    setInputRef.current = setInput;
  }, [setInput]);

  // Detect when user manually edits input (deletes text)
  useEffect(() => {
    if (isListening && !isUpdatingFromSpeechRef.current) {
      // Input changed but not from speech recognition
      // User must have manually edited it
      if (input !== lastSpeechInputRef.current) {
        console.log("User manually edited input, updating base");
        baseInputRef.current = input;
        lastSpeechInputRef.current = input;
      }
    }
    
    // If input is empty and we were listening, reset base
    if (input === "" && baseInputRef.current !== "") {
      console.log("Input cleared, resetting base");
      baseInputRef.current = "";
      lastSpeechInputRef.current = "";
    }
    
    isUpdatingFromSpeechRef.current = false;
  }, [input, isListening]);

  // Initialize Speech Recognition ONCE
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      ("SpeechRecognition" in window || "webkitSpeechRecognition" in window)
    ) {
      const SpeechRecognition =
        (window as any).SpeechRecognition ||
        (window as any).webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      
      // Auto-detect language - support multiple languages
      // Browser will detect which language is being spoken
      recognition.lang = "th-TH";
      recognition.maxAlternatives = 3;

      recognition.onstart = () => {
        console.log("Speech recognition started");
        isActiveRef.current = true;
        setIsListening(true);
        // Reset processed results count on each start
        processedResultsCountRef.current = 0;
      };

      recognition.onresult = (event: any) => {
        // Only process if we're supposed to be listening
        if (!isActiveRef.current) return;

        let interimTranscript = "";
        let finalTranscript = "";
        
        // Process only results we haven't processed yet
        for (let i = processedResultsCountRef.current; i < event.results.length; ++i) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
            // Mark this result as processed
            processedResultsCountRef.current = i + 1;
          } else {
            interimTranscript += transcript;
          }
        }

        // Combine base input with transcripts
        const baseInput = baseInputRef.current;
        const trailingSpace = baseInput.length > 0 && !baseInput.endsWith(" ") ? " " : "";
        
        // Mark that we're updating from speech
        isUpdatingFromSpeechRef.current = true;
        
        if (finalTranscript) {
          // Append only the NEW final transcript to base
          const newBase = baseInput + trailingSpace + finalTranscript;
          baseInputRef.current = newBase;
          lastSpeechInputRef.current = newBase;
          setInputRef.current(newBase);
          
          console.log("New final transcript:", finalTranscript, "Base:", baseInputRef.current);
        } else if (interimTranscript) {
          // Show interim results in real-time (temporary)
          const tempInput = baseInput + trailingSpace + interimTranscript;
          lastSpeechInputRef.current = tempInput;
          setInputRef.current(tempInput);
        }
      };

      recognition.onerror = (event: any) => {
        console.error("Speech recognition error", event.error);
        
        // Ignore aborted errors when we're stopping intentionally
        if (event.error === "aborted" && !isActiveRef.current) {
          return;
        }
        
        isActiveRef.current = false;
        setIsListening(false);
        
        if (event.error === "network") {
          setSpeechError("Network error: Check connection");
        } else if (event.error === "not-allowed") {
          setSpeechError("Microphone denied");
        } else if (event.error !== "aborted") {
          setSpeechError("Speech failed");
        }
        setTimeout(() => setSpeechError(null), 3000);
      };

      recognition.onend = () => {
        console.log("Speech recognition ended");
        
        // If we're still supposed to be listening, restart it
        if (isActiveRef.current) {
          console.log("Restarting speech recognition...");
          try {
            recognition.start();
          } catch (e) {
            console.error("Error restarting recognition:", e);
            isActiveRef.current = false;
            setIsListening(false);
          }
        } else {
          // Only set to false if we intentionally stopped
          setIsListening(false);
        }
      };

      recognitionRef.current = recognition;
    }

    // Cleanup on unmount
    return () => {
      if (recognitionRef.current) {
        isActiveRef.current = false;
        try {
          recognitionRef.current.abort();
        } catch (e) {
          console.error("Error aborting recognition on cleanup:", e);
        }
      }
    };
  }, []); // Empty dependency - initialize only once!

  const toggleListening = useCallback(() => {
    if (!recognitionRef.current) {
      setSpeechError("Speech recognition not supported");
      setTimeout(() => setSpeechError(null), 3000);
      return;
    }

    if (isListening || isActiveRef.current) {
      // Force stop listening
      console.log("Stopping speech recognition...");
      isActiveRef.current = false;
      setIsListening(false);
      
      try {
        // Use abort() instead of stop() for immediate termination
        recognitionRef.current.abort();
      } catch (e) {
        console.error("Error stopping recognition:", e);
      }
    } else {
      // Start listening
      console.log("Starting speech recognition...");
      try {
        // Store current input as base before starting
        baseInputRef.current = input;
        lastSpeechInputRef.current = input;
        isActiveRef.current = true;
        recognitionRef.current.start();
        setSpeechError(null);
      } catch (e) {
        console.error("Error starting recognition:", e);
        isActiveRef.current = false;
        setIsListening(false);
        setSpeechError("Failed to start recording");
        setTimeout(() => setSpeechError(null), 3000);
      }
    }
  }, [isListening, input]);

  return {
    isListening,
    speechError,
    toggleListening,
  };
};
