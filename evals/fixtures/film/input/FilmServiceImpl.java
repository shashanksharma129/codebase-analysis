package com.example.app.services.catalog.service;

import com.example.app.common.exception.ResourceNotFoundException;
import com.example.app.services.catalog.domain.dto.ActorDto;
import com.example.app.services.catalog.domain.dto.FilmDetailsDto;
import com.example.app.services.catalog.domain.dto.FilmDto;
import com.example.app.services.catalog.domain.mapper.FilmMapper;
import com.example.app.services.catalog.repository.FilmRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class FilmServiceImpl implements FilmService {
    private final FilmRepository filmRepository;
    private final FilmMapper filmMapper;

    @Override
    @Transactional(readOnly = true)
    public List<FilmDto.Film> getFilmList() {
        final var list = filmRepository.findAll();
        return filmMapper.mapToDtoList(list);
    }

    @Override
    @Transactional(readOnly = true)
    public List<FilmDto.Film> getFilmList(FilmDto.FilterOption condition, Pageable pageable) {
        return (condition.areAllFieldsNull())
                ? filmRepository.findAllFilmList(pageable)
                : filmRepository.findAllFilmListWithFilter(condition, pageable);
    }

    @Override
    @Transactional(readOnly = true)
    @Cacheable(value = "filmResponseCache", key = "#filmId")
    public Optional<FilmDto.Film> getFilm(Integer filmId) {
        final var entity = filmRepository.findById(filmId).orElseThrow(() ->
                new ResourceNotFoundException("Film not found with id '" + filmId + "'"));
        return Optional.of(filmMapper.mapToDto(entity));
    }

    @Override
    @Transactional(readOnly = true)
    public List<ActorDto.Actor> getFilmActorList(Integer filmId, Pageable pageable) {
        return filmRepository.findAllFilmActorListById(filmId, pageable);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<ActorDto.Actor> getFilmActor(Integer filmId, Integer actorId) {
        final var model = filmRepository.findFilmActorById(filmId, actorId);
        if (model.isEmpty()) {
            throw new ResourceNotFoundException("Actor not found with id '" + actorId + "'");
        }
        return model;
    }

    @Override
    @Transactional(readOnly = true)
    public List<FilmDetailsDto.FilmDetails> getFilmDetailsList() {
        return filmRepository.findAllFilmListDetail();
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<FilmDetailsDto.FilmDetails> getFilmDetails(Integer filmId) {
        final var model = filmRepository.findFilmDetailsById(filmId);
        if (model.isEmpty()) {
            throw new ResourceNotFoundException("Film not found with id '" + filmId + "'");
        }
        return model;
    }

    @Override
    @Transactional(readOnly = true)
    public BigDecimal getFilmRentalPrice(Integer filmId) {
        final var model = filmRepository.findRentalRateByFilmId(filmId);
        if (model.getRentalRate() == null) {
            throw new ResourceNotFoundException("Film not found with id '" + filmId + "'");
        }
        return model.getRentalRate();
    }

    @Override
    @Transactional
    public FilmDto.Film addFilm(FilmDto.FilmRequest model) {
        final var savedEntity = filmRepository.save(filmMapper.mapToEntity(model));
        return filmMapper.mapToDto(savedEntity);
    }

    @Override
    @Transactional
    @CachePut(value = "filmResponseCache", key = "#filmId")
    public FilmDto.Film updateFilm(Integer filmId, FilmDto.FilmRequest model) {
        final var entity = filmRepository.findById(filmId).orElseThrow(() ->
                new ResourceNotFoundException("Film not found with id '" + filmId + "'"));
        entity.update(filmMapper.mapToEntity(model));
        return filmMapper.mapToDto(entity);
    }

    @Override
    @Transactional
    @CacheEvict(value = "filmResponseCache", key = "#filmId")
    public void deleteFilm(Integer filmId) {
        filmRepository.deleteById(filmId);
    }
}
