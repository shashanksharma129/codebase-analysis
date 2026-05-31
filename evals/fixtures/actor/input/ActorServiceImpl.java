package com.example.app.services.catalog.service;

import com.example.app.common.exception.ResourceNotFoundException;
import com.example.app.services.catalog.domain.dto.ActorDetailsDto;
import com.example.app.services.catalog.domain.dto.ActorDto;
import com.example.app.services.catalog.domain.dto.FilmDetailsDto;
import com.example.app.services.catalog.domain.dto.FilmDto;
import com.example.app.services.catalog.domain.mapper.ActorMapper;
import com.example.app.services.catalog.repository.ActorRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class ActorServiceImpl implements ActorService {
    private final ActorRepository actorRepository;
    private final ActorMapper actorMapper;

    @Override
    @Transactional(readOnly = true)
    public List<ActorDto.Actor> getActorList(Pageable pageable) {
        final var list = actorRepository.findAll(pageable);
        return actorMapper.mapToDtoList(list);
    }

    @Override
    @Transactional(readOnly = true)
    @Cacheable(value = "actorResponseCache", key = "#actorId")
    public Optional<ActorDto.Actor> getActor(Integer actorId) {
        final var entity = actorRepository.findById(actorId).orElseThrow(() ->
                new ResourceNotFoundException("Actor not found with id '" + actorId + "'"));
        return Optional.of(actorMapper.mapToDto(entity));
    }

    @Override
    @Transactional(readOnly = true)
    public List<ActorDetailsDto.ActorDetails> getActorDetailsList() {
        return actorRepository.findAllActorDetailsList();
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<ActorDetailsDto.ActorDetails> getActorDetails(Integer actorId) {
        final var model = actorRepository.findActorDetailsById(actorId);
        if (model.isEmpty()) {
            throw new ResourceNotFoundException("Actor not found with id '" + actorId + "'");
        }
        return model;
    }

    @Override
    @Transactional(readOnly = true)
    public List<FilmDto.Film> getActorFilmList(Integer actorId, FilmDto.FilterOption condition, Pageable pageable) {
        return actorRepository.findAllActorFilmListByIdWithCondition(actorId, condition, pageable);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<FilmDto.Film> getActorFilm(Integer actorId, Integer filmId) {
        final var model = actorRepository.findActorFilmById(actorId, filmId);
        if (model.isEmpty()) {
            throw new ResourceNotFoundException("Actor not found with id '" + actorId + "'");
        }
        return model;
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<FilmDetailsDto.FilmDetails> getActorFilmDetails(Integer actorId, Integer filmId) {
        final var model = actorRepository.findActorFilmDetailsById(actorId, filmId);
        if (model.isEmpty()) {
            throw new ResourceNotFoundException("Actor not found with id '" + actorId + "'");
        }
        return model;
    }

    @Override
    @Transactional(readOnly = true)
    public List<ActorDto.Actor> searchActorList(String name) {
        final var list = actorRepository.findActorEntitiesByFullNameFirstNameContainsOrFullNameLastNameContains(name, name);
        if (list.isEmpty()) {
            throw new ResourceNotFoundException("Actor not found with name '" + name + "'");
        }
        return actorMapper.mapToDtoList(list);
    }

    @Override
    @Transactional
    public ActorDto.Actor addActor(ActorDto.ActorRequest model) {
        final var savedEntity = actorRepository.save(actorMapper.mapToEntity(model));
        return actorMapper.mapToDto(savedEntity);
    }

    @Override
    @Transactional
    public FilmDto.Film addActorFilm(Integer actorId, Integer filmId) {
        return actorRepository.addActorFilm(actorId, filmId).orElseThrow(() ->
                new ResourceNotFoundException("Actor not found with id '" + actorId + "'"));
    }

    @Override
    @Transactional
    @CachePut(value = "actorResponseCache", key = "#actorId")
    public ActorDto.Actor updateActor(Integer actorId, ActorDto.ActorRequest model) {
        final var entity = actorRepository.findById(actorId).orElseThrow(() ->
                new ResourceNotFoundException("Actor not found with id '" + actorId + "'"));
        entity.update(actorMapper.mapToEntity(model));
        return actorMapper.mapToDto(entity);
    }

    @Override
    @Transactional
    @CacheEvict(value = "actorResponseCache", key = "#actorId")
    public void deleteActor(Integer actorId) {
        actorRepository.deleteById(actorId);
    }

    @Override
    @Transactional
    public void removeActorFilm(Integer actorId, Integer filmId) {
        actorRepository.removeActorFilm(actorId, filmId);
    }
}
